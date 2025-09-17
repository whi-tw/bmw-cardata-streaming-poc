#!/usr/bin/env python3
"""
BMW CarData MQTT Client with OAuth2 Device Code Flow Authentication

This script authenticates with BMW CarData using OAuth2 Device Code Flow
and connects to the MQTT streaming service to receive real-time vehicle data.

Environment Variables Required:
- BMW_CLIENT_ID: Your BMW CarData client ID
- BMW_VIN: Vehicle VIN to subscribe to

Optional:
- BMW_MQTT_HOST: MQTT broker hostname (default: customer.streaming-cardata.bmwgroup.com)
- BMW_MQTT_PORT: MQTT broker port (default: 9000)
- BMW_TOKEN_FILE: Path to token storage file (default: bmw_tokens.json)
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import time
import webbrowser
from datetime import datetime, timedelta
from typing import Any, Dict

import paho.mqtt.client as mqtt
import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv is optional; environment variables can be set directly


class BMWCarDataClient:
    """BMW CarData client with OAuth2 Device Code Flow and MQTT streaming."""

    def __init__(self, log_raw_messages=False):
        # Load configuration from environment
        self.client_id = os.getenv("BMW_CLIENT_ID")
        self.mqtt_host = os.getenv(
            "BMW_MQTT_HOST", "customer.streaming-cardata.bmwgroup.com"
        )
        self.mqtt_port = int(os.getenv("BMW_MQTT_PORT", "9000"))
        self.vin = os.getenv("BMW_VIN")
        self.token_file = os.getenv("BMW_TOKEN_FILE", "bmw_tokens.json")
        self.log_raw_messages = log_raw_messages

        # Validate required environment variables
        required_vars = [
            "BMW_CLIENT_ID",
            "BMW_VIN",
        ]
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )

        # OAuth endpoints
        self.device_code_url = "https://customer.bmwgroup.com/gcdm/oauth/device/code"
        self.token_url = "https://customer.bmwgroup.com/gcdm/oauth/token"

        # Token storage
        self.tokens = {}
        self.mqtt_client = None

    @property
    def mqtt_username(self) -> str:
        """Get MQTT username (GCID) from stored tokens."""
        if "gcid" in self.tokens:
            return self.tokens["gcid"]
        raise ValueError("GCID not available - authentication required")

    def _generate_pkce_pair(self) -> tuple[str, str]:
        """Generate PKCE code verifier and code challenge."""
        # Generate code verifier (43-128 characters)
        code_verifier = (
            base64.urlsafe_b64encode(secrets.token_bytes(32))
            .decode("utf-8")
            .rstrip("=")
        )

        # Generate code challenge using S256 method
        code_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("utf-8")).digest()
            )
            .decode("utf-8")
            .rstrip("=")
        )

        return code_verifier, code_challenge

    def _save_tokens(self):
        """Save tokens to disk for persistence."""
        try:
            with open(self.token_file, "w") as f:
                json.dump(self.tokens, f, indent=2)
            print(f"Tokens saved to {self.token_file}")
        except Exception as e:
            print(f"Warning: Could not save tokens to {self.token_file}: {e}")

    def _load_tokens(self) -> bool:
        """Load tokens from disk if available."""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, "r") as f:
                    self.tokens = json.load(f)
                print(f"Tokens loaded from {self.token_file}")
                return True
        except Exception as e:
            print(f"Warning: Could not load tokens from {self.token_file}: {e}")
        return False

    def _is_token_expired(self, token_key: str) -> bool:
        """Check if a token is expired or will expire soon."""
        if token_key not in self.tokens or "expires_at" not in self.tokens[token_key]:
            return True

        expires_at = datetime.fromisoformat(self.tokens[token_key]["expires_at"])
        # Consider token expired if it expires in the next 5 minutes
        return datetime.now() + timedelta(minutes=5) >= expires_at

    def authenticate(self) -> bool:
        """Perform OAuth2 Device Code Flow authentication."""
        # Try to load existing tokens
        if self._load_tokens():
            # Check if we have a valid access token or can refresh
            if not self._is_token_expired("access_token"):
                print("Using existing valid access token")
                return True
            elif "refresh_token" in self.tokens and not self._is_token_expired(
                "refresh_token"
            ):
                print("Access token expired, attempting to refresh...")
                if self._refresh_tokens():
                    return True
                print("Token refresh failed, proceeding with new authentication...")

        print("Starting OAuth2 Device Code Flow authentication...")

        # Step 1: Generate PKCE pair
        code_verifier, code_challenge = self._generate_pkce_pair()

        # Step 2: Request device and user codes
        device_code_data = {
            "client_id": self.client_id,
            "response_type": "device_code",
            "scope": "authenticate_user openid cardata:streaming:read cardata:api:read",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            response = requests.post(
                self.device_code_url, data=device_code_data, headers=headers, timeout=30
            )
            response.raise_for_status()
            device_response = response.json()
        except requests.RequestException as e:
            print(f"Error requesting device code: {e}")
            return False

        # Extract response data
        user_code = device_response["user_code"]
        device_code = device_response["device_code"]
        verification_uri_complete = device_response["verification_uri_complete"]
        expires_in = device_response["expires_in"]
        interval = device_response.get("interval", 5)

        # Step 3: Display user instructions
        print("\n" + "=" * 60)
        print("BMW CarData Authentication Required")
        print("=" * 60)
        print(f"User Code: {user_code}")
        print(f"Please visit: {verification_uri_complete}")
        print("\nOR manually visit the verification URL and enter the user code.")
        print("Complete the authentication in your browser, then return here.")
        print("=" * 60)

        # Optionally open browser automatically
        try:
            webbrowser.open(verification_uri_complete)
            print("Browser opened automatically. If not, please visit the URL above.")
        except Exception:
            print(
                "Could not open browser automatically. Please visit the URL manually."
            )

        # Step 4: Poll for tokens
        token_data = {
            "client_id": self.client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "code_verifier": code_verifier,
        }

        start_time = time.time()
        while time.time() - start_time < expires_in:
            print(
                f"Waiting for authentication... ({int(expires_in - (time.time() - start_time))}s remaining)"
            )
            time.sleep(interval)

            try:
                token_response = requests.post(
                    self.token_url, data=token_data, headers=headers, timeout=30
                )

                if token_response.status_code == 200:
                    # Success! We got the tokens
                    tokens = token_response.json()
                    self._store_tokens(tokens)
                    print("Authentication successful!")
                    return True
                elif token_response.status_code == 403:
                    # Check error type
                    error_data = token_response.json()
                    error = error_data.get("error", "")

                    if error == "authorization_pending":
                        continue  # Keep waiting
                    elif error == "access_denied":
                        print("Authentication was denied by the user.")
                        return False
                    else:
                        print(f"Authentication error: {error}")
                        return False
                elif token_response.status_code == 400:
                    error_data = token_response.json()
                    if error_data.get("error") == "slow_down":
                        # Increase polling interval
                        interval += 5
                        continue
                    else:
                        print(f"Bad request: {error_data}")
                        return False
                else:
                    print(
                        f"Unexpected response: {token_response.status_code} - {token_response.text}"
                    )

            except requests.RequestException as e:
                print(f"Error polling for tokens: {e}")
                time.sleep(interval)
                continue

        print("Authentication timed out. Please try again.")
        return False

    def _store_tokens(self, tokens: Dict[str, Any]):
        """Store tokens with expiration timestamps."""
        now = datetime.now()

        # Store access token
        if "access_token" in tokens:
            expires_in = tokens.get("expires_in", 3600)
            self.tokens["access_token"] = {
                "token": tokens["access_token"],
                "expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
                "type": tokens.get("token_type", "Bearer"),
            }

        # Store refresh token (valid for 2 weeks)
        if "refresh_token" in tokens:
            self.tokens["refresh_token"] = {
                "token": tokens["refresh_token"],
                "expires_at": (now + timedelta(seconds=1209600)).isoformat(),  # 2 weeks
            }

        # Store ID token (for MQTT)
        if "id_token" in tokens:
            expires_in = tokens.get("expires_in", 3600)
            self.tokens["id_token"] = {
                "token": tokens["id_token"],
                "expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
            }

        # Store other data
        if "gcid" in tokens:
            self.tokens["gcid"] = tokens["gcid"]
        if "scope" in tokens:
            self.tokens["scope"] = tokens["scope"]

        self._save_tokens()

    def _refresh_tokens(self) -> bool:
        """Refresh access and ID tokens using refresh token."""
        if "refresh_token" not in self.tokens:
            print("No refresh token available")
            return False

        refresh_data = {
            "grant_type": "refresh_token",
            "refresh_token": self.tokens["refresh_token"]["token"],
            "client_id": self.client_id,
        }

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            response = requests.post(
                self.token_url, data=refresh_data, headers=headers, timeout=30
            )
            response.raise_for_status()
            tokens = response.json()
            self._store_tokens(tokens)
            print("Tokens refreshed successfully")
            return True
        except requests.RequestException as e:
            print(f"Error refreshing tokens: {e}")
            return False

    def _ensure_valid_tokens(self) -> bool:
        """Ensure we have valid tokens, refreshing if necessary."""
        if self._is_token_expired("id_token"):
            if "refresh_token" in self.tokens and not self._is_token_expired(
                "refresh_token"
            ):
                print("ID token expired, refreshing...")
                return self._refresh_tokens()
            else:
                print("ID token expired and cannot refresh, need new authentication")
                return self.authenticate()
        return True

    def _on_connect(self, client, userdata, flags, rc, properties):
        """MQTT connection callback."""
        if rc.value == 0:
            print("Connected to MQTT broker successfully")

            topic = f"{self.mqtt_username}/{self.vin}"
            client.subscribe(topic, qos=1)
            print(f"Subscribed to topic: {topic} with QoS 1")

            wildcard_topic = f"{self.mqtt_username}/+"
            client.subscribe(wildcard_topic, qos=1)
            print(f"Subscribed to wildcard topic: {wildcard_topic} with QoS 1")

            expires_at = datetime.fromisoformat(self.tokens["id_token"]["expires_at"])
            time_until_expiry = expires_at - datetime.now()
            print(f"ID token expires in: {time_until_expiry}")

            if hasattr(flags, "session_present"):
                print(f"Session present: {flags.session_present}")
        else:
            print(f"Failed to connect to MQTT broker: {rc.name}")

    def _on_message(self, client, userdata, msg):
        """MQTT message callback."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data = json.loads(msg.payload.decode())

            if self.log_raw_messages:
                print(f"\n[{timestamp}] Message Received:")
                print(f"Topic: {msg.topic}")
                print(f"QoS: {msg.qos}")
                print(f"Retain: {msg.retain}")
                print(f"Data: {json.dumps(data, indent=2)}")
            else:
                # Try to parse BMW CarData message structure
                if self._parse_bmw_message(data, timestamp):
                    return

                # Fallback to raw JSON if parsing fails
                print(f"\n[{timestamp}] Raw message: {json.dumps(data)}")

        except json.JSONDecodeError:
            print(f"Received non-JSON message: {msg.payload.decode()}")
        except Exception as e:
            print(f"Error processing message: {e}")

    def _parse_bmw_message(self, data, timestamp):
        """Parse BMW CarData message into readable format."""
        try:
            if not isinstance(data, dict) or "data" not in data:
                return False

            vin = data.get("vin", "Unknown")
            msg_timestamp = data.get("timestamp", "Unknown")
            vehicle_data = data.get("data", {})

            print(f"\n[{timestamp}] Vehicle Event - {vin}")
            print(f"Event time: {msg_timestamp}")

            # Parse each data point
            for key, value in vehicle_data.items():
                if (
                    isinstance(value, dict)
                    and "value" in value
                    and "timestamp" in value
                ):
                    print(f"  {key}: {value['value']} (at {value['timestamp']})")
                else:
                    print(f"  {key}: {value}")

            return True

        except Exception:
            return False

    def _on_log(self, client, userdata, level, buf):
        """MQTT logging callback for debugging."""
        log_levels = {
            mqtt.MQTT_LOG_ERR: "ERROR",
            mqtt.MQTT_LOG_WARNING: "WARNING",
            mqtt.MQTT_LOG_NOTICE: "NOTICE",
            mqtt.MQTT_LOG_INFO: "INFO",
            mqtt.MQTT_LOG_DEBUG: "DEBUG",
        }
        level_name = log_levels.get(level, f"LEVEL_{level}")
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] MQTT {level_name}: {buf}")

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        """MQTT subscription callback."""
        print(f"Subscription confirmed - Message ID: {mid}")
        for i, rc in enumerate(reason_codes):
            print(f"Topic {i}: {rc}")

    def _on_disconnect(self, client, userdata, flags, rc, properties):
        """MQTT disconnect callback."""
        if rc.value != 0:
            print(f"Unexpected disconnection from MQTT broker: {rc.name}")

            if rc.value in (4, 5):
                print("Possible token expiration - checking token validity...")
                if self._is_token_expired("id_token"):
                    print(
                        "ID token has expired, will refresh on next connection attempt"
                    )
            else:
                print("Attempting to reconnect...")

    def connect_mqtt(self) -> bool:
        """Connect to MQTT broker for streaming."""
        if not self._ensure_valid_tokens():
            print("Cannot connect to MQTT: No valid tokens")
            return False

        if "id_token" not in self.tokens:
            print("Cannot connect to MQTT: No ID token")
            return False

        print("Connecting to MQTT broker...")

        self.mqtt_client = mqtt.Client(
            protocol=mqtt.MQTTv5,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_subscribe = self._on_subscribe
        self.mqtt_client.on_disconnect = self._on_disconnect

        if os.getenv("MQTT_LOGGING", "").lower() in ("true", "1", "yes", "on"):
            self.mqtt_client.on_log = self._on_log

        self.mqtt_client.tls_set()

        id_token = self.tokens["id_token"]["token"]
        self.mqtt_client.username_pw_set(self.mqtt_username, id_token)

        try:
            connect_properties = mqtt.Properties(mqtt.PacketTypes.CONNECT)
            connect_properties.SessionExpiryInterval = 0  # Clean start
            self.mqtt_client.connect(
                self.mqtt_host, self.mqtt_port, 30, properties=connect_properties
            )
            self.mqtt_client.loop_start()
            return True
        except Exception as e:
            print(f"Error connecting to MQTT broker: {e}")
            return False

    def run_credentials_only(self):
        """Run in credentials-only mode - just print MQTT connection info."""
        print("BMW CarData Credentials Provider Starting...")

        # Authenticate
        if not self.authenticate():
            print("Authentication failed. Exiting.")
            return

        # Print initial connection info
        print("\n" + "=" * 60)
        print("MQTT Connection Information")
        print("=" * 60)
        print(f"Host: {self.mqtt_host}")
        print(f"Port: {self.mqtt_port}")
        print(f"Username: {self.mqtt_username}")
        print(f"Topic: {self.mqtt_username}/{self.vin}")
        print("=" * 60)

        if "id_token" not in self.tokens:
            print("No ID token available for password")
            return

        # Print initial password
        id_token = self.tokens["id_token"]["token"]
        expires_at = datetime.fromisoformat(self.tokens["id_token"]["expires_at"])
        print(f"Password: {id_token}")
        print(f"Expires: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print("\nPress Ctrl+C to exit.")

        try:
            while True:
                time.sleep(60)

                if self._is_token_expired("id_token"):
                    print(
                        f"\n[{datetime.now().strftime('%H:%M:%S')}] Token expiring soon, refreshing..."
                    )
                    if not self._ensure_valid_tokens():
                        print("Failed to refresh tokens. Exiting.")
                        break

                    if "id_token" in self.tokens:
                        id_token = self.tokens["id_token"]["token"]
                        expires_at = datetime.fromisoformat(
                            self.tokens["id_token"]["expires_at"]
                        )
                        print(f"Updated Password: {id_token}")
                        print(f"Expires: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")

        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            print("BMW CarData Credentials Provider stopped.")

    def run(self):
        """Main run loop."""
        print("BMW CarData MQTT Client Starting...")

        # Authenticate
        if not self.authenticate():
            print("Authentication failed. Exiting.")
            return

        # Connect to MQTT
        if not self.connect_mqtt():
            print("MQTT connection failed. Exiting.")
            return

        print("\nStreaming vehicle data... Press Ctrl+C to exit.")

        try:
            while True:
                time.sleep(60)

                if self._is_token_expired("id_token"):
                    print("ID token expiring soon, refreshing...")
                    if not self._ensure_valid_tokens():
                        print("Failed to refresh tokens, reconnecting...")
                        self.mqtt_client.disconnect()
                        if not self.connect_mqtt():
                            print("Failed to reconnect. Exiting.")
                            break

        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            if self.mqtt_client:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            print("BMW CarData MQTT Client stopped.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="BMW CarData MQTT Client with OAuth2 Device Code Flow Authentication"
    )
    parser.add_argument(
        "--credentials-only",
        action="store_true",
        help="Only print MQTT connection credentials and refresh tokens, don't connect to MQTT",
    )
    parser.add_argument(
        "--log-raw-messages",
        action="store_true",
        help="Log raw MQTT messages instead of parsed vehicle events",
    )

    args = parser.parse_args()

    try:
        client = BMWCarDataClient(log_raw_messages=args.log_raw_messages)
        if args.credentials_only:
            client.run_credentials_only()
        else:
            client.run()
    except ValueError as e:
        print(f"Configuration error: {e}")
        print("\nRequired environment variables:")
        print("- BMW_CLIENT_ID: Your BMW CarData client ID")
        print("- BMW_VIN: Vehicle VIN to subscribe to")
        print("\nOptional environment variables:")
        print(
            "- BMW_MQTT_HOST: MQTT broker hostname (default: customer.streaming-cardata.bmwgroup.com)"
        )
        print("- BMW_MQTT_PORT: MQTT broker port (default: 9000)")
        print("- BMW_TOKEN_FILE: Token storage file (default: bmw_tokens.json)")
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
