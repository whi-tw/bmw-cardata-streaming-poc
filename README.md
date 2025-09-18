# BMW CarData MQTT Client

A Python client for BMW CarData that authenticates using OAuth2 Device Code Flow and streams real-time vehicle data via MQTT.

## Features

- **Standalone library** (`bmw_cardata.py`) for easy integration
- **OAuth2 Device Code Flow** authentication with PKCE
- **Automatic token refresh** and persistence
- **Real-time MQTT streaming** of vehicle data with QoS 1
- **Human-readable message display** using BMW's official data catalogue
- **Credentials-only mode** for external MQTT clients
- **MQTT v5.0** with clean session handling
- **Callback-based architecture** for flexible integration

## Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/whi-tw/bmw-cardata-streaming-poc.git
   cd bmw-cardata-streaming-poc
   ```

2. Install dependencies:

   ```bash
   uv install
   ```

   **If you aren't using `uv`:**

   ```bash
   pip install -r requirements.txt
   ```

3. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

4. Edit `.env` with your BMW CarData credentials:
   ```bash
   export BMW_CLIENT_ID="your-client-id"
   export BMW_VIN="your-vehicle-vin"
   ```

## Authentication

Before you can use this client, you need:

- A BMW CarData client ID from your BMW customer portal
- Your vehicle mapped as the PRIMARY user in your BMW account
- Active BMW CarData subscription

For a complete technical guide to BMW's OAuth2 Device Code Flow authentication process, including step-by-step implementation details for other programming languages, see [AUTHENTICATION.md](AUTHENTICATION.md).

## Data Catalogue

The client can optionally use BMW's official data catalogue to display human-readable names and units for telematic data points.

### Download Data Catalogue

To get the latest BMW CarData catalogue with descriptions and units:

```bash
uv run bmw_catalogue.py --refresh
```

This fetches BMW's official telematic data catalogue from their API and caches it locally in `bmw_data_catalogue.json`. The applications automatically use this cached data to enhance message display with human-readable names and units.

You can also explore the catalogue data:

```bash
# Show catalogue statistics
uv run bmw_catalogue.py --stats

# List all categories with descriptions
uv run bmw_catalogue.py --list-categories

# Search for specific data points
uv run bmw_catalogue.py --search "door"

# List items by category
uv run bmw_catalogue.py --category "VEHICLE_STATUS"
```

## Architecture

The project consists of three main components:

- **`bmw_cardata.py`** - Standalone library handling authentication and MQTT
- **`bmw_catalogue.py`** - Catalogue library for fetching and caching BMW's official data catalogue
- **`main.py`** - CLI application with display logic and message formatting
- **`webui.py`** - Web dashboard with real-time visualization and WebSocket updates

### Library Usage

You can use the library directly in your own projects:

```python
from bmw_cardata import BMWCarDataClient

# Create client
client = BMWCarDataClient(
    client_id="your-client-id",
    vin="your-vin",
)

# Set up callbacks
client.set_message_callback(lambda topic, data: print(f"Got data: {data}"))
client.set_connect_callback(lambda: print("Connected!"))

# Authenticate and connect
if client.authenticate():
    client.connect_mqtt()
```

## Usage

### Stream Vehicle Data

Run the client to authenticate and stream vehicle data:

```bash
uv run main.py
# or if not using uv:
python main.py
```

On first run, you'll be prompted to authenticate via your browser. The client will:

1. Open your browser to BMW's authentication page
2. Display a user code to enter
3. Wait for you to complete authentication
4. Save tokens for future use
5. Connect to MQTT and stream vehicle data

#### Message Logging Options

By default, messages are parsed into a readable format with human-readable names:

```
[2025-09-17 13:18:22] Vehicle Event - WBAJE5C55KG123456
Event time: 2025-09-17T12:18:21.396Z
  Status of rear left door: false (at 2025-09-17T12:18:19Z)
```

To see raw MQTT messages with full JSON data and technical keys:

```bash
uv run main.py --log-raw-messages
```

### Web Dashboard (Example)

For a visual example of using the MQTT data:

```bash
uv run webui.py
```

This launches a simple web dashboard at `http://localhost:5000` that demonstrates real-time data visualization using the BMW CarData stream.

### Get MQTT Credentials Only

To get MQTT connection credentials without connecting (useful for external MQTT clients):

```bash
uv run main.py --credentials-only
# or if not using uv:
python main.py --credentials-only
```

This will output connection details and keep tokens refreshed:

```
MQTT Connection Information
============================================================
Host: customer.streaming-cardata.bmwgroup.com
Port: 9000
Username: your-gcid (automatically obtained from authentication)
Topic: your-gcid/your-vin
============================================================
Password: eyJhbGciOiJSUzI1NiIs...
Expires: 2024-01-01 15:30:00
```

## Environment Variables

Required:

- `BMW_CLIENT_ID`: Your BMW CarData client ID
- `BMW_VIN`: Vehicle VIN to subscribe to

Optional:

- `BMW_MQTT_HOST`: MQTT broker hostname (default: customer.streaming-cardata.bmwgroup.com)
- `BMW_MQTT_PORT`: MQTT broker port (default: 9000)
- `BMW_TOKEN_FILE`: Path to token storage file (default: bmw_tokens.json)
- `MQTT_DEBUG`: Enable detailed MQTT debug logging including keepalive messages (set to "true", "1", "yes", or "on")

## Token Management

Tokens are automatically saved to `bmw_tokens.json` and refreshed as needed:

- Access tokens: Valid for ~1 hour
- Refresh tokens: Valid for 2 weeks
- ID tokens: Used as MQTT password, valid for ~1 hour

The client automatically refreshes tokens before they expire.

## Debugging

### MQTT Debug Logging

To troubleshoot MQTT connection issues, enable detailed debug logging:

```bash
export MQTT_DEBUG=true
uv run main.py
```

This will show detailed MQTT protocol messages including:
- Connection establishment and TLS handshake details
- Keepalive/ping messages between client and broker
- Subscription confirmations and QoS handling
- Network socket activity and timeouts
- Authentication and credential exchange
- Disconnection reasons and error codes

Debug messages are formatted with precise timestamps:
```
[13:18:22.145] MQTT(16): Sending CONNECT (b0, ...)
[13:18:22.234] MQTT(16): Received CONNACK (20, 0)
[13:18:22.235] MQTT(16): Sending SUBSCRIBE (82, ...)
[13:18:37.145] MQTT(16): Sending PINGREQ
[13:18:37.187] MQTT(16): Received PINGRESP
```

Note: Debug logging will temporarily set the logger to DEBUG level to ensure all MQTT messages are visible.

## Disclaimer

This is a proof-of-concept implementation for educational and development purposes. Use at your own risk and ensure compliance with BMW's terms of service and applicable data protection regulations.
