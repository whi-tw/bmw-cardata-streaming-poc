#!/usr/bin/env python3
"""
BMW CarData MQTT Client

CLI application for BMW CarData streaming with human-readable message display.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

from bmw_cardata import BMWCarDataClient
from bmw_catalogue import BMWCatalogueClient

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv is optional


class BMWCarDataApp:
    """Main application class for BMW CarData streaming."""

    def __init__(self, log_raw_messages: bool = False):
        self.log_raw_messages = log_raw_messages
        self.catalogue_client = BMWCatalogueClient()
        self.client = None
        self.running = False

    def _format_data_point(self, key: str, value: Any, timestamp: str) -> str:
        """Format a data point with catalogue information."""
        display_name = self.catalogue_client.get_display_name(key)
        unit = self.catalogue_client.get_unit(key)

        # Format the value with unit if available
        value_str = str(value)
        if unit:
            value_str = f"{value} {unit}"

        return f"{display_name}: {value_str} (at {timestamp})"

    def _parse_bmw_message(self, data: dict, timestamp: str) -> bool:
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
                    formatted_line = self._format_data_point(
                        key, value["value"], value["timestamp"]
                    )
                    print(f"  {formatted_line}")
                else:
                    print(f"  {key}: {value}")

            return True

        except Exception:
            return False

    def on_message(self, topic: str, data: dict):
        """Handle incoming MQTT messages."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.log_raw_messages:
            print(f"\n[{timestamp}] Message Received:")
            print(f"Topic: {topic}")
            print(f"Data: {json.dumps(data, indent=2)}")
        else:
            # Try to parse BMW CarData message structure
            if not self._parse_bmw_message(data, timestamp):
                # Fallback to raw JSON if parsing fails
                print(f"\n[{timestamp}] Raw message: {json.dumps(data)}")

    def on_connect(self):
        """Handle MQTT connection success."""
        print("Successfully connected and subscribed to vehicle data")

    def on_disconnect(self, reason_code: int):
        """Handle MQTT disconnection."""
        if reason_code != 0:
            print(f"Lost connection to MQTT broker (code: {reason_code})")

    def on_token_refresh(self, token_info: dict):
        """Handle token refresh for credentials-only mode."""
        if hasattr(self, "_credentials_mode") and self._credentials_mode:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Token refreshed")
            print(f"Updated Password: {token_info['mqtt_password']}")
            expires_at = datetime.fromisoformat(token_info["expires_at"])
            print(f"Expires: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")

    def run_streaming(self):
        """Run in streaming mode."""
        print("BMW CarData MQTT Client Starting...")

        # Get configuration from environment
        client_id = os.getenv("BMW_CLIENT_ID")
        vin = os.getenv("BMW_VIN")
        mqtt_host = os.getenv(
            "BMW_MQTT_HOST", "customer.streaming-cardata.bmwgroup.com"
        )
        mqtt_port = int(os.getenv("BMW_MQTT_PORT", "9000"))
        token_file = os.getenv("BMW_TOKEN_FILE", "bmw_tokens.json")

        # Validate required variables
        if not client_id or not vin:
            raise ValueError(
                "Missing required environment variables: BMW_CLIENT_ID, BMW_VIN"
            )

        # Create client
        self.client = BMWCarDataClient(
            client_id=client_id,
            vin=vin,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            token_file=token_file,
        )

        # Set callbacks
        self.client.set_message_callback(self.on_message)
        self.client.set_connect_callback(self.on_connect)
        self.client.set_disconnect_callback(self.on_disconnect)

        # Authenticate
        if not self.client.authenticate():
            print("Authentication failed. Exiting.")
            return

        # Connect to MQTT
        if not self.client.connect_mqtt():
            print("MQTT connection failed. Exiting.")
            return

        print("\nStreaming vehicle data... Press Ctrl+C to exit.")
        self.running = True

        try:
            # Monitor tokens
            self.client.run_token_monitor(stop_callback=lambda: not self.running)
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self.running = False
            if self.client:
                self.client.disconnect_mqtt()
            print("BMW CarData MQTT Client stopped.")

    def run_credentials_only(self):
        """Run in credentials-only mode."""
        print("BMW CarData Credentials Provider Starting...")
        self._credentials_mode = True

        # Get configuration from environment
        client_id = os.getenv("BMW_CLIENT_ID")
        vin = os.getenv("BMW_VIN")
        mqtt_host = os.getenv(
            "BMW_MQTT_HOST", "customer.streaming-cardata.bmwgroup.com"
        )
        mqtt_port = int(os.getenv("BMW_MQTT_PORT", "9000"))
        token_file = os.getenv("BMW_TOKEN_FILE", "bmw_tokens.json")

        # Validate required variables
        if not client_id or not vin:
            raise ValueError(
                "Missing required environment variables: BMW_CLIENT_ID, BMW_VIN"
            )

        # Create client
        self.client = BMWCarDataClient(
            client_id=client_id,
            vin=vin,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            token_file=token_file,
        )

        # Set token refresh callback
        self.client.set_token_refresh_callback(self.on_token_refresh)

        # Authenticate
        if not self.client.authenticate():
            print("Authentication failed. Exiting.")
            return

        # Print initial connection info
        print("\n" + "=" * 60)
        print("MQTT Connection Information")
        print("=" * 60)
        print(f"Host: {mqtt_host}")
        print(f"Port: {mqtt_port}")
        print(f"Username: {self.client.mqtt_username}")
        print(f"Topic: {self.client.mqtt_username}/{vin}")
        print("=" * 60)

        if "id_token" not in self.client.tokens:
            print("No ID token available for password")
            return

        # Print initial password
        id_token = self.client.tokens["id_token"]["token"]
        expires_at = datetime.fromisoformat(
            self.client.tokens["id_token"]["expires_at"]
        )
        print(f"Password: {id_token}")
        print(f"Expires: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print("\nPress Ctrl+C to exit.")

        self.running = True

        try:
            # Monitor tokens
            self.client.run_token_monitor(stop_callback=lambda: not self.running)
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            self.running = False
            print("BMW CarData Credentials Provider stopped.")


def main():
    """Main entry point."""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

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
        app = BMWCarDataApp(log_raw_messages=args.log_raw_messages)
        if args.credentials_only:
            app.run_credentials_only()
        else:
            app.run_streaming()
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
    sys.exit(main())
