# BMW CarData Authentication Flow

This document explains the OAuth2 Device Code Flow authentication process for BMW CarData in plain English, allowing you to implement this flow in other projects or programming languages.

## Overview

BMW CarData uses OAuth2 Device Code Flow with PKCE (Proof Key for Code Exchange) for authentication. This flow is designed for devices that don't have a web browser or have limited input capabilities.

## Prerequisites

Before starting, you need:

1. A BMW CarData client ID (generated in your BMW customer portal)
2. Your vehicle mapped to your BMW account as the PRIMARY user
3. Subscription to BMW CarData services in the customer portal

## Step-by-Step Authentication Process

### Step 1: Generate PKCE Code Pair

Generate a cryptographically secure code verifier and challenge:

1. **Code Verifier**: Generate a random 32-byte value, base64url-encode it, and remove padding
2. **Code Challenge**: SHA256 hash the code verifier, base64url-encode the result, and remove padding

```
code_verifier = base64url_encode(random_bytes(32)).strip('=')
code_challenge = base64url_encode(sha256(code_verifier)).strip('=')
```

### Step 2: Request Device and User Codes

Make a POST request to the device authorization endpoint:

**URL**: `https://customer.bmwgroup.com/gcdm/oauth/device/code`

**Headers**:

- `Accept: application/json`
- `Content-Type: application/x-www-form-urlencoded`

**Body Parameters**:

- `client_id`: Your BMW CarData client ID
- `response_type`: `device_code`
- `scope`: `authenticate_user openid cardata:streaming:read cardata:api:read`
- `code_challenge`: The code challenge from Step 1
- `code_challenge_method`: `S256`

**Response** contains:

- `user_code`: Code for user to enter in browser
- `device_code`: Used for polling (keep this secure)
- `verification_uri_complete`: URL user should visit
- `expires_in`: How long codes are valid (seconds)
- `interval`: Minimum seconds between polling requests

### Step 3: User Authentication

1. Display the `user_code` to the user
2. Tell them to visit the `verification_uri_complete` URL
3. Optionally open their browser automatically to this URL
4. User logs into BMW portal and authorizes the device

### Step 4: Poll for Tokens

While waiting for user authentication, poll the token endpoint:

**URL**: `https://customer.bmwgroup.com/gcdm/oauth/token`

**Headers**:

- `Content-Type: application/x-www-form-urlencoded`

**Body Parameters**:

- `client_id`: Your BMW CarData client ID
- `device_code`: From Step 2 response
- `grant_type`: `urn:ietf:params:oauth:grant-type:device_code`
- `code_verifier`: From Step 1

**Polling Logic**:

- Wait at least `interval` seconds between requests
- Continue until `expires_in` time is reached
- Handle these response codes:
  - **200**: Success! You got the tokens
  - **403 with `authorization_pending`**: Keep waiting
  - **403 with `access_denied`**: User denied access
  - **400 with `slow_down`**: Increase polling interval by 5 seconds

**Successful Response** contains:

- `access_token`: For BMW CarData API calls (1 hour validity)
- `refresh_token`: For refreshing tokens (2 weeks validity)
- `id_token`: For MQTT authentication (1 hour validity)
- `token_type`: Usually "Bearer"
- `expires_in`: Access token lifetime in seconds
- `scope`: Granted scopes
- `gcid`: Your BMW customer ID

### Step 5: Store Tokens Securely

Store the tokens with their expiration times:

- Access token expires in `expires_in` seconds
- ID token expires in `expires_in` seconds
- Refresh token expires in 1,209,600 seconds (2 weeks)

Calculate expiration timestamps by adding the lifetime to the current time.

### Step 6: Refresh Tokens When Needed

Before tokens expire (recommend 5-minute buffer), refresh them:

**URL**: `https://customer.bmwgroup.com/gcdm/oauth/token`

**Headers**:

- `Content-Type: application/x-www-form-urlencoded`

**Body Parameters**:

- `grant_type`: `refresh_token`
- `refresh_token`: Your current refresh token
- `client_id`: Your BMW CarData client ID

This returns new access, ID, and refresh tokens with reset expiration times.

## Using the Tokens

### For BMW CarData API

Use the `access_token` in the Authorization header:

```
Authorization: Bearer <access_token>
```

### For MQTT Streaming

Use these credentials:

- **Host**: `customer.streaming-cardata.bmwgroup.com`
- **Port**: `9000`
- **Username**: Your `gcid` from token response
- **Password**: The `id_token`
- **Topic**: `<gcid>/<vin>` for specific vehicle, or `<gcid>/*` for all vehicles
- **SSL/TLS**: Required

## Important Notes

1. **Only one MQTT connection per user** allowed at a time
2. **Refresh tokens proactively** - don't wait until they expire
3. **Store tokens securely** - they provide full access to vehicle data
4. **Handle token expiration gracefully** - implement automatic refresh
5. **Rate limits**: API has 50 requests/day limit; use streaming for frequent access

## Error Handling

Common errors and solutions:

- **Token expired**: Refresh using refresh token
- **Invalid scope**: Re-authenticate with correct scopes
- **No permission for VIN**: Ensure vehicle is mapped as PRIMARY user
- **Connection failed**: Check network, SSL/TLS settings
- **Authentication pending**: Continue polling with proper interval

## Security Considerations

- Never log or expose tokens in plain text
- Use secure storage for token persistence
- Implement proper error handling to avoid token leakage
- Use HTTPS/TLS for all communications
- Validate SSL certificates
- Implement token rotation and cleanup

## What is the "User Code"?

**Important:** The user code displayed during authentication (like "ab92WX1l") is a temporary authorization code for OAuth2 Device Code Flow applications only. It is **NOT** related to your physical vehicle in any way.

### Common Confusion

Some users think the code might be:

- ❌ A code they'll receive in their car's display
- ❌ A code sent via BMW's mobile app
- ❌ A service code for their vehicle
- ❌ Something physical related to their car

### What it Actually Is

The user code is:

- ✅ A temporary (usually 15-minute) authorization code
- ✅ Generated by BMW's authentication servers
- ✅ Used only to link OAuth2 applications to your BMW account
- ✅ Displayed on your computer screen by the application
- ✅ Entered on BMW's website (not in your car)

### The Process

1. **You run an OAuth2 application** → It requests access to your BMW data
2. **BMW's servers generate a code** → Like "ABC-123"
3. **The application displays the code** → On your computer screen
4. **You visit BMW's website** → Either via the direct link or the "Authenticate Device" button
5. **You enter the code** → If using the "Authenticate Device" option
6. **You authorize the application** → Using your BMW login
7. **The application gets access** → To your BMW data

### BMW Portal "Authenticate Device" Button

If you see an "Authenticate Device" button in your BMW customer portal, **this is what it's for!** This button leads to `https://customer.bmwgroup.com/oneid/link` where you can manually enter the user code displayed by any OAuth2 application.

This button exists specifically for scenarios like this - when third-party applications need authorization but you can't click the direct link (e.g., the code is displayed on a different device).

The user code is simply BMW's way of securely connecting third-party applications to your BMW account without sharing your login credentials.
