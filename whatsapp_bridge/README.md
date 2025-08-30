# WhatsApp Bridge

A Node.js bridge that connects WhatsApp to the Python backend using the Baileys library.

## Features

- **Headless Operation**: No Chrome dependency required
- **Session Management**: Automatic session persistence and restoration
- **Persistent Chat Cache**: Chats survive reconnections
- **REST API**: Full API for client management
- **Auto-reconnection**: Automatic reconnection on disconnects
- **Webhook Integration**: Seamless integration with Python backend

## Installation

```bash
npm install
```

## Usage

### Start the bridge
```bash
npm start
```

### Development mode
```bash
npm run dev
```

## API Endpoints

- `GET /health` - Bridge health status
- `POST /initialize/:userId` - Initialize a new client
- `POST /cleanup/:userId` - Clean up a client
- `GET /status/:userId` - Get client status
- `GET /chats/:userId` - Get user's chats
- `GET /qr/:userId` - Get QR code for authentication
- `POST /restore-all` - Restore all clients from disk
- `POST /disconnect/:userId` - Disconnect a client
- `POST /reconnect/:userId` - Reconnect a client

## Environment Variables

- `PYTHON_BACKEND_URL` - Python backend URL (default: http://127.0.0.1:9876)
- `WHATSAPP_SESSION_PATH` - Session storage path (default: ./sessions)
- `INIT_TIMEOUT_MS` - Initialization timeout (default: 45000)
- `MAX_INIT_RETRIES` - Max initialization retries (default: 2)
- `RESTORE_DELAY_MS` - Restore delay (default: 3000)

## Architecture

The bridge uses Baileys (`@whiskeysockets/baileys`) for WhatsApp connectivity and provides a REST API for the Python backend to manage WhatsApp clients. It includes:

- **Session Persistence**: Automatic session storage and restoration
- **Persistent Chat Cache**: Chats are cached and survive reconnections
- **Event Handling**: Proper handling of WhatsApp events
- **Error Recovery**: Automatic reconnection and error handling

## Benefits over whatsapp-web.js

- **No Chrome Dependency**: Runs headless without requiring Chrome/Puppeteer
- **Better Performance**: More efficient resource usage
- **Simplified Deployment**: No need for Chrome installation
- **Reliable Reconnection**: Better handling of connection issues
