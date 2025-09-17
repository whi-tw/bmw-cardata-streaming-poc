#!/usr/bin/env python3
"""
BMW CarData Web UI

A Flask web interface for BMW CarData streaming with real-time WebSocket updates.
"""

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template
from flask_socketio import SocketIO, emit

from bmw_cardata import BMWCarDataClient
from bmw_catalogue import BMWCatalogueClient

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = "bmw-cardata-webui"
socketio = SocketIO(app, cors_allowed_origins="*")

# Global state
client = None
current_data = {}
catalogue_client = None
connection_status = "disconnected"
CACHE_FILE = "bmw_webui_cache.json"


def format_data_point(key: str, value: Any) -> dict:
    """Format a data point with catalogue information."""
    result = {
        "key": key,
        "value": value,
        "display_name": key,
        "unit": None,
        "category": None,
        "category_description": None,
        "category_rank": None,
        "datatype": None,
    }

    if catalogue_client:
        result["display_name"] = catalogue_client.get_display_name(key)
        result["unit"] = catalogue_client.get_unit(key)
        result["category"] = catalogue_client.get_category(key)
        result["datatype"] = catalogue_client.get_datatype(key)
        if result["category"]:
            result["category_description"] = catalogue_client.get_category_description(
                result["category"]
            )
            result["category_rank"] = catalogue_client.get_category_rank(
                result["category"]
            )

    return result


def load_cached_data():
    """Load cached data from previous session."""
    global current_data
    try:
        if Path(CACHE_FILE).exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cached_data = json.load(f)

                # Ensure all cached data has current category metadata
                if catalogue_client:
                    for key, data in cached_data.items():
                        # Add or update category metadata
                        data["category"] = catalogue_client.get_category(key)
                        category = data.get("category")
                        if category:
                            data["category_description"] = (
                                catalogue_client.get_category_description(category)
                            )
                            data["category_rank"] = catalogue_client.get_category_rank(
                                category
                            )
                        data["datatype"] = catalogue_client.get_datatype(key)

                current_data = cached_data
                logger.info(f"Loaded {len(current_data)} cached data points")
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Could not load cached data: {e}")


def save_cached_data():
    """Save current data to cache file."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(current_data, f, indent=2)
        logger.debug(f"Saved {len(current_data)} data points to cache")
    except IOError as e:
        logger.warning(f"Could not save cached data: {e}")


def on_message(topic: str, data: dict):
    """Handle incoming MQTT messages."""
    global current_data

    try:
        if not isinstance(data, dict) or "data" not in data:
            return

        vin = data.get("vin", "Unknown")
        msg_timestamp = data.get("timestamp", "Unknown")
        vehicle_data = data.get("data", {})

        # Process each data point
        updates = []
        for key, value_data in vehicle_data.items():
            if (
                isinstance(value_data, dict)
                and "value" in value_data
                and "timestamp" in value_data
            ):
                formatted = format_data_point(key, value_data["value"])
                formatted["timestamp"] = value_data["timestamp"]
                formatted["changed"] = (
                    current_data.get(key, {}).get("value") != value_data["value"]
                )

                current_data[key] = {
                    "value": value_data["value"],
                    "timestamp": value_data["timestamp"],
                    "display_name": formatted["display_name"],
                    "unit": formatted["unit"],
                    "category": formatted["category"],
                    "category_description": formatted["category_description"],
                    "category_rank": formatted["category_rank"],
                    "datatype": formatted["datatype"],
                }

                updates.append(formatted)

        # Emit updates to all connected clients
        if updates:
            socketio.emit(
                "data_update",
                {"vin": vin, "timestamp": msg_timestamp, "updates": updates},
            )

            # Save cached data periodically (every update for now)
            save_cached_data()

        logger.info(f"Processed {len(updates)} data points for VIN {vin}")

    except Exception as e:
        logger.error(f"Error processing MQTT message: {e}")


def on_connect():
    """Handle MQTT connection success."""
    global connection_status
    connection_status = "connected"
    socketio.emit("connection_status", {"status": "connected"})
    logger.info("MQTT connected")


def on_disconnect(reason_code: int):
    """Handle MQTT disconnection."""
    global connection_status
    connection_status = "disconnected"
    socketio.emit(
        "connection_status", {"status": "disconnected", "reason": reason_code}
    )
    logger.warning(f"MQTT disconnected with code: {reason_code}")


def on_token_refresh(token_info: dict):
    """Handle token refresh."""
    logger.info("MQTT tokens refreshed")
    socketio.emit("token_refresh", {"timestamp": datetime.now().isoformat()})


def start_bmw_client():
    """Start the BMW CarData client in a separate thread."""
    global client

    # Get configuration from environment
    client_id = os.getenv("BMW_CLIENT_ID")
    vin = os.getenv("BMW_VIN")
    mqtt_host = os.getenv("BMW_MQTT_HOST", "customer.streaming-cardata.bmwgroup.com")
    mqtt_port = int(os.getenv("BMW_MQTT_PORT", "9000"))
    token_file = os.getenv("BMW_TOKEN_FILE", "bmw_tokens.json")

    if not client_id or not vin:
        logger.error("Missing required environment variables: BMW_CLIENT_ID, BMW_VIN")
        return False

    # Create client
    client = BMWCarDataClient(
        client_id=client_id,
        vin=vin,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        token_file=token_file,
    )

    # Set callbacks
    client.set_message_callback(on_message)
    client.set_connect_callback(on_connect)
    client.set_disconnect_callback(on_disconnect)
    client.set_token_refresh_callback(on_token_refresh)

    # Authenticate
    if not client.authenticate():
        logger.error("Authentication failed")
        return False

    # Connect to MQTT
    if not client.connect_mqtt():
        logger.error("MQTT connection failed")
        return False

    logger.info("BMW CarData client started successfully")

    # Start token monitoring
    try:
        client.run_token_monitor()
    except Exception as e:
        logger.error(f"Token monitor error: {e}")

    return True


@app.route("/")
def index():
    """Main dashboard page."""
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    """Get current connection status."""
    return jsonify(
        {
            "connection_status": connection_status,
            "data_points": len(current_data),
            "timestamp": datetime.now().isoformat(),
        }
    )


@app.route("/api/data")
def api_data():
    """Get current vehicle data."""
    return jsonify({"data": current_data, "timestamp": datetime.now().isoformat()})


@socketio.on("connect")
def handle_connect():
    """Handle WebSocket client connection."""
    logger.info("WebSocket client connected")
    emit("connection_status", {"status": connection_status})
    if current_data:
        emit("initial_data", {"data": current_data})


@socketio.on("disconnect")
def handle_disconnect():
    """Handle WebSocket client disconnection."""
    logger.info("WebSocket client disconnected")


def main():
    """Main entry point."""
    global catalogue_client

    # Initialize catalogue client
    catalogue_client = BMWCatalogueClient()
    stats = catalogue_client.get_stats()
    logger.info(f"Loaded {stats['total_items']} catalogue entries from cache")

    # Load cached data from previous session
    load_cached_data()

    # Start BMW client in background thread
    bmw_thread = threading.Thread(target=start_bmw_client, daemon=True)
    bmw_thread.start()

    # Start web server
    logger.info("Starting BMW CarData Web UI on http://localhost:5000")
    socketio.run(
        app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True
    )


if __name__ == "__main__":
    main()
