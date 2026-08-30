# How WhatsApp Integration Works

## Two separate WhatsApp stacks

Do not conflate these when debugging:

| Stack | Library | Direction | Used for |
|-------|---------|-----------|----------|
| Bridge | [Baileys](https://github.com/WhiskeySockets/Baileys) (`@whiskeysockets/baileys`) | inbound | receiving messages, QR pairing, chat list |
| Business API | Meta Cloud API (HTTP) | outbound | delivering digests (`app/whatsapp/official_service.py`) |

This document is about the **bridge**.

## Connection architecture

```
WhatsApp servers  ←(WebSocket, Baileys)→  Node bridge (:3000)  →  FastAPI (:9876)
                                               ↓
                              whatsapp_sessions/ (creds + state files)
```

Baileys speaks the WhatsApp multi-device protocol over a WebSocket directly.
There is **no** Puppeteer, no headless Chrome, and no `.wwebjs_cache/` — those
belong to `whatsapp-web.js`, which this project no longer uses.

**Connections are persistent, not per-request:**

- Sockets are opened when the bridge starts and stay open.
- Incoming messages are pushed to the backend via webhook in real time.
- Digest generation never opens a WhatsApp connection; it only reads messages
  already stored in Postgres.

## What happens on container restart

1. **Session persistence.** Baileys credentials are written by
   `useMultiFileAuthState()` into `${WHATSAPP_SESSION_PATH}/session-{user_id}/`
   (default `/app/whatsapp_sessions` in the container). This path must be a
   persistent volume — losing it means every user has to re-scan a QR code.

2. **Automatic restoration.** `docker/start.sh` starts the bridge with
   `RESTORE_ON_START=0` and then calls `POST /restore-all` once the API is
   answering, so restoration can validate user ids against the backend:

   ```javascript
   async restoreAllClients() {
     // fetch active, non-suspended users from the backend
     // drop stale persisted state (validateAndCleanupPersistedState)
     // re-open a socket per remaining user
   }
   ```

3. **Connection monitoring.** The bridge periodically re-checks every socket,
   reconnects on `connection.close`, and reports status changes to the backend
   (which can notify over Telegram).

## When a connection is established

- On bridge startup (restoration of existing sessions).
- When a new user pairs (QR scan).
- When an existing socket drops (automatic reconnect).

## Bridge internals (`whatsapp_bridge/bridge.js`)

```javascript
class BaileysWhatsAppBridge {
  constructor() {
    this.clients = new Map();           // userId -> WASocket
    this.clientStates = new Map();      // userId -> state info
    this.qrCodes = new Map();           // userId -> qr string
    this.reconnectTimeouts = new Map(); // userId -> timeout
    this.persistentChats = new Map();   // userId -> cached chats
  }
}
```

Key behaviours:

- Connection state is persisted to `${WHATSAPP_SESSION_PATH}/client_states.json`
  (older builds wrote it into the bridge working directory; that legacy file is
  migrated on startup).
- Stale persisted state can be cleared with `POST /cleanup-stale-state` — see
  [WHATSAPP_BRIDGE_TROUBLESHOOTING.md](WHATSAPP_BRIDGE_TROUBLESHOOTING.md).
- Graceful shutdown flushes state before exiting.

## Inbound message flow

`app/api/whatsapp_webhooks.py`:

```python
@router.post("/webhook/whatsapp/message")
async def receive_whatsapp_message():
    # authenticate the bridge call
    # store the message
    # score importance via OpenAI in the background
    # send an urgent notification if importance is high enough
```

```
WhatsApp → Baileys bridge → FastAPI webhook → Postgres → (digest on schedule)
                                            ↓
                                  urgent notifications
```

Suspended users get an HTTP **200** with a "suspended" detail rather than an
error, so the bridge does not retry-storm.

## Related user fields

`app/models/database.py` tracks bridge state on `User`:

- `whatsapp_connected` — last known socket state
- `whatsapp_session_id` — session identifier
- `whatsapp_last_seen` — last activity timestamp
