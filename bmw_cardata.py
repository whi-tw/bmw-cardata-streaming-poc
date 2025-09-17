"""
BMW CarData Client Library

A standalone library for BMW CarData OAuth2 authentication and MQTT streaming.
Handles authentication, token management, and MQTT connection lifecycle.
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import paho.mqtt.client as mqtt
import requests

logger = logging.getLogger(__name__)


class BMWCarDataClient:
    """BMW CarData client with OAuth2 Device Code Flow and MQTT streaming."""

    def __init__(
        self,
        client_id: str,
        vin: str,
        mqtt_host: str = "customer.streaming-cardata.bmwgroup.com",
        mqtt_port: int = 9000,
        token_file: str = "bmw_tokens.json",
        subscribe_wildcard: bool = True,
    ):
        """
        Initialize BMW CarData client.

        Args:
            client_id: BMW CarData client ID
            vin: Vehicle VIN
            mqtt_host: MQTT broker hostname
            mqtt_port: MQTT broker port
            token_file: Path to token storage file
            subscribe_wildcard: Whether to subscribe to wildcard topic (GCID/+)
        """
        self.client_id = client_id
        self.vin = vin
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.token_file = token_file
        self.subscribe_wildcard = subscribe_wildcard

        # OAuth endpoints
        self.device_code_url = "https://customer.bmwgroup.com/gcdm/oauth/device/code"
        self.token_url = "https://customer.bmwgroup.com/gcdm/oauth/token"

        # State
        self.tokens = {}
        self.mqtt_client = None

        # Callbacks
        self.message_callback: Optional[Callable] = None
        self.connect_callback: Optional[Callable] = None
        self.disconnect_callback: Optional[Callable] = None
        self.token_refresh_callback: Optional[Callable] = None

    @property
    def mqtt_username(self) -> str:
        """Get MQTT username (GCID) from stored tokens."""
        if "gcid" in self.tokens:
            return self.tokens["gcid"]
        raise ValueError("GCID not available - authentication required")

    def set_message_callback(self, callback: Callable[[str, Any], None]):
        """Set callback for MQTT messages. Callback receives (topic, data)."""
        self.message_callback = callback

    def set_connect_callback(self, callback: Callable[[], None]):
        """Set callback for successful MQTT connection."""
        self.connect_callback = callback

    def set_disconnect_callback(self, callback: Callable[[int], None]):
        """Set callback for MQTT disconnection. Callback receives reason code."""
        self.disconnect_callback = callback

    def set_token_refresh_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Set callback for token refresh. Callback receives token data."""
        self.token_refresh_callback = callback

    def _generate_pkce_pair(self) -> tuple[str, str]:
        """Generate PKCE code verifier and code challenge."""
        code_verifier = (
            base64.urlsafe_b64encode(secrets.token_bytes(32))
            .decode("utf-8")
            .rstrip("=")
        )

        code_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("utf-8")).digest()
            )
            .decode("utf-8")
            .rstrip("=")
        )

        return code_verifier, code_challenge

    def _save_tokens_selective(self):
        """Save only refresh token and metadata to disk for persistence."""
        persistent_tokens = {}

        if "refresh_token" in self.tokens:
            persistent_tokens["refresh_token"] = self.tokens["refresh_token"]
        if "gcid" in self.tokens:
            persistent_tokens["gcid"] = self.tokens["gcid"]
        if "scope" in self.tokens:
            persistent_tokens["scope"] = self.tokens["scope"]

        try:
            with open(self.token_file, "w") as f:
                json.dump(persistent_tokens, f, indent=2)
            logger.info(f"Refresh token saved to {self.token_file}")
        except Exception as e:
            logger.warning(f"Could not save tokens to {self.token_file}: {e}")

    def _load_tokens(self) -> bool:
        """Load tokens from disk if available."""
        try:
            if Path(self.token_file).exists():
                with open(self.token_file, "r") as f:
                    self.tokens = json.load(f)
                logger.info(f"Tokens loaded from {self.token_file}")
                return True
        except Exception as e:
            logger.warning(f"Could not load tokens from {self.token_file}: {e}")
        return False

    def _is_token_expired(self, token_key: str) -> bool:
        """Check if a token is expired or will expire soon."""
        if token_key not in self.tokens or "expires_at" not in self.tokens[token_key]:
            return True

        expires_at = datetime.fromisoformat(self.tokens[token_key]["expires_at"])
        return datetime.now() + timedelta(minutes=5) >= expires_at

    def authenticate(self) -> bool:
        """Perform OAuth2 Device Code Flow authentication."""
        # Always refresh tokens on startup for fresh hour-long session
        if (
            self._load_tokens()
            and "refresh_token" in self.tokens
            and not self._is_token_expired("refresh_token")
        ):
            logger.info("Refreshing tokens for fresh session...")
            if self._refresh_tokens():
                return True
            logger.warning(
                "Token refresh failed, proceeding with new authentication..."
            )

        logger.info("Starting OAuth2 Device Code Flow authentication...")

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
            logger.error(f"Error requesting device code: {e}")
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
            logger.info(
                f"Waiting for authentication... ({int(expires_in - (time.time() - start_time))}s remaining)"
            )
            time.sleep(interval)

            try:
                token_response = requests.post(
                    self.token_url, data=token_data, headers=headers, timeout=30
                )

                if token_response.status_code == 200:
                    tokens = token_response.json()
                    self._store_tokens(tokens)
                    logger.info("Authentication successful!")
                    return True
                elif token_response.status_code == 403:
                    error_data = token_response.json()
                    error = error_data.get("error", "")

                    if error == "authorization_pending":
                        continue
                    elif error == "access_denied":
                        logger.error("Authentication was denied by the user.")
                        return False
                    else:
                        logger.error(f"Authentication error: {error}")
                        return False
                elif token_response.status_code == 400:
                    error_data = token_response.json()
                    if error_data.get("error") == "slow_down":
                        interval += 5
                        continue
                    else:
                        logger.error(f"Bad request: {error_data}")
                        return False
                else:
                    logger.error(
                        f"Unexpected response: {token_response.status_code} - {token_response.text}"
                    )

            except requests.RequestException as e:
                logger.error(f"Error polling for tokens: {e}")
                time.sleep(interval)
                continue

        logger.error("Authentication timed out. Please try again.")
        return False

    def _store_tokens(self, tokens: Dict[str, Any]):
        """Store tokens with expiration timestamps."""
        now = datetime.now()

        # Store access token (in memory only, not persisted)
        if "access_token" in tokens:
            expires_in = tokens.get("expires_in", 3600)
            self.tokens["access_token"] = {
                "token": tokens["access_token"],
                "expires_at": (now + timedelta(seconds=expires_in)).isoformat(),
                "type": tokens.get("token_type", "Bearer"),
            }

        # Store refresh token (persisted for future use)
        if "refresh_token" in tokens:
            self.tokens["refresh_token"] = {
                "token": tokens["refresh_token"],
                "expires_at": (now + timedelta(seconds=1209600)).isoformat(),  # 2 weeks
            }

        # Store ID token (in memory only, not persisted)
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

        self._save_tokens_selective()

        # Call token refresh callback if set
        if self.token_refresh_callback:
            token_info = {
                "gcid": self.tokens.get("gcid"),
                "mqtt_host": self.mqtt_host,
                "mqtt_port": self.mqtt_port,
                "mqtt_username": self.tokens.get("gcid"),
                "mqtt_password": self.tokens.get("id_token", {}).get("token"),
                "topic": f"{self.tokens.get('gcid')}/{self.vin}",
                "expires_at": self.tokens.get("id_token", {}).get("expires_at"),
            }
            self.token_refresh_callback(token_info)

    def _refresh_tokens(self) -> bool:
        """Refresh access and ID tokens using refresh token."""
        if "refresh_token" not in self.tokens:
            logger.error("No refresh token available")
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
            logger.info("Tokens refreshed successfully")
            return True
        except requests.RequestException as e:
            logger.error(f"Error refreshing tokens: {e}")
            return False

    def _ensure_valid_tokens(self) -> bool:
        """Ensure we have valid tokens, refreshing if necessary."""
        if self._is_token_expired("id_token"):
            if "refresh_token" in self.tokens and not self._is_token_expired(
                "refresh_token"
            ):
                logger.info("ID token expired, refreshing...")
                return self._refresh_tokens()
            else:
                logger.error(
                    "ID token expired and cannot refresh, need new authentication"
                )
                return self.authenticate()
        return True

    def _on_connect(self, client, userdata, flags, rc, properties):
        """MQTT connection callback."""
        if rc.value == 0:
            logger.info("Connected to MQTT broker successfully")

            topic = f"{self.mqtt_username}/{self.vin}"
            client.subscribe(topic, qos=1)
            logger.info(f"Subscribed to topic: {topic} with QoS 1")

            if self.subscribe_wildcard:
                wildcard_topic = f"{self.mqtt_username}/+"
                client.subscribe(wildcard_topic, qos=1)
                logger.info(
                    f"Subscribed to wildcard topic: {wildcard_topic} with QoS 1"
                )
            else:
                logger.info("Wildcard subscription disabled")

            expires_at = datetime.fromisoformat(self.tokens["id_token"]["expires_at"])
            time_until_expiry = expires_at - datetime.now()
            logger.info(f"ID token expires in: {time_until_expiry}")

            if hasattr(flags, "session_present"):
                logger.debug(f"Session present: {flags.session_present}")

            if self.connect_callback:
                self.connect_callback()
        else:
            logger.error(f"Failed to connect to MQTT broker: {rc}")

    def _on_message(self, client, userdata, msg):
        """MQTT message callback."""
        try:
            data = json.loads(msg.payload.decode())

            if self.message_callback:
                self.message_callback(msg.topic, data)
            else:
                logger.info(f"Received message on {msg.topic}: {data}")

        except json.JSONDecodeError:
            logger.warning(f"Received non-JSON message: {msg.payload.decode()}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        """MQTT subscription callback."""
        logger.debug(f"Subscription confirmed - Message ID: {mid}")
        for i, rc in enumerate(reason_codes):
            logger.debug(f"Topic {i}: {rc}")

    def _on_disconnect(self, client, userdata, flags, rc, properties):
        """MQTT disconnect callback."""
        if rc.value != 0:
            logger.warning(f"Unexpected disconnection from MQTT broker: {rc}")

            if rc.value in (4, 5):
                logger.info("Possible token expiration - checking token validity...")
                if self._is_token_expired("id_token"):
                    logger.warning(
                        "ID token has expired, will refresh on next connection attempt"
                    )
            else:
                logger.info("Attempting to reconnect...")

            if self.disconnect_callback:
                self.disconnect_callback(rc.value)

    def _on_log(self, _client, _userdata, level, buf):
        """MQTT logging callback for debug output."""
        # Map MQTT log levels to Python logging levels
        # PAHO MQTT uses integer constants: 16=DEBUG, 8=INFO, 4=NOTICE, 2=WARNING, 1=ERROR
        level_map = {
            16: logging.DEBUG,  # MQTT_LOG_DEBUG
            8: logging.INFO,  # MQTT_LOG_INFO
            4: logging.INFO,  # MQTT_LOG_NOTICE
            2: logging.WARNING,  # MQTT_LOG_WARNING
            1: logging.ERROR,  # MQTT_LOG_ERR
        }
        py_level = level_map.get(level, logging.INFO)

        # Format with timestamp and level info for better debugging
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        logger.log(py_level, f"[{timestamp}] MQTT({level}): {buf}")

    def connect_mqtt(self) -> bool:
        """Connect to MQTT broker for streaming."""
        if not self._ensure_valid_tokens():
            logger.error("Cannot connect to MQTT: No valid tokens")
            return False

        if "id_token" not in self.tokens:
            logger.error("Cannot connect to MQTT: No ID token")
            return False

        logger.info("Connecting to MQTT broker...")

        self.mqtt_client = mqtt.Client(
            protocol=mqtt.MQTTv5,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_subscribe = self._on_subscribe
        self.mqtt_client.on_disconnect = self._on_disconnect

        # Enable MQTT debug logging if requested
        if os.getenv("MQTT_DEBUG", "").lower() in ("true", "1", "yes", "on"):
            self.mqtt_client.on_log = self._on_log
            self.mqtt_client.enable_logger()
            # Temporarily set logger to DEBUG level for MQTT messages
            mqtt_logger = logging.getLogger("bmw_cardata")
            mqtt_logger.setLevel(logging.DEBUG)
            logger.info("MQTT debug logging enabled")

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
            logger.error(f"Error connecting to MQTT broker: {e}")
            return False

    def disconnect_mqtt(self):
        """Disconnect from MQTT broker."""
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

    def run_token_monitor(self, stop_callback: Optional[Callable[[], bool]] = None):
        """
        Monitor and refresh tokens as needed.

        Args:
            stop_callback: Optional callback that returns True to stop monitoring
        """
        while True:
            time.sleep(60)  # Check every minute

            if stop_callback and stop_callback():
                break

            if self._is_token_expired("id_token"):
                logger.info("ID token expiring soon, refreshing...")
                if not self._ensure_valid_tokens():
                    logger.error("Failed to refresh tokens")
                    if self.mqtt_client:
                        logger.info("Reconnecting MQTT...")
                        self.mqtt_client.disconnect()
                        if not self.connect_mqtt():
                            logger.error("Failed to reconnect MQTT")
                            break
                else:
                    # Token refresh succeeded, update MQTT credentials
                    if self.mqtt_client and "id_token" in self.tokens:
                        logger.info("Updating MQTT credentials with new tokens...")
                        new_id_token = self.tokens["id_token"]["token"]
                        self.mqtt_client.username_pw_set(
                            self.mqtt_username, new_id_token
                        )

                        # Reconnect with updated credentials
                        logger.info("Reconnecting MQTT with refreshed credentials...")
                        self.mqtt_client.disconnect()
                        if not self.connect_mqtt():
                            logger.error(
                                "Failed to reconnect MQTT with new credentials"
                            )
                            break
