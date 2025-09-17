# BMW CarData MQTT Client (POC)

A proof-of-concept Python client for BMW CarData that authenticates using OAuth2 Device Code Flow and streams real-time vehicle data via MQTT.

## Features

- OAuth2 Device Code Flow authentication with PKCE
- Automatic token refresh and persistence
- Real-time MQTT streaming of vehicle data with QoS 1
- Credentials-only mode for external MQTT clients
- MQTT v5.0 with clean session handling

## Setup

1. Install dependencies:
   ```bash
   uv install
   ```
   
   **If you aren't using `uv`:**
   ```bash
   pip install -r requirements.txt
   ```

2. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

3. Edit `.env` with your BMW CarData credentials:
   ```bash
   export BMW_CLIENT_ID="your-client-id"
   export BMW_VIN="your-vehicle-vin"
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
- `MQTT_LOGGING`: Enable detailed MQTT logging (set to "true", "1", "yes", or "on")

## Token Management

Tokens are automatically saved to `bmw_tokens.json` and refreshed as needed:
- Access tokens: Valid for ~1 hour
- Refresh tokens: Valid for 2 weeks  
- ID tokens: Used as MQTT password, valid for ~1 hour

The client automatically refreshes tokens before they expire.

## Disclaimer

This is a proof-of-concept implementation for educational and development purposes. Use at your own risk and ensure compliance with BMW's terms of service and applicable data protection regulations.