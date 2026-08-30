# WhatsApp Bridge Troubleshooting Guide

## Issue: Client State Mismatch

### Problem Description
The WhatsApp bridge shows as healthy but fails to retrieve chats with the error:
```
{"error":"Client not ready after timeout","chats":[]}
```

### Root Cause
This issue occurs when there's a mismatch between:
1. **Persisted bridge state**: The bridge's `client_states.json` contains stale user IDs
2. **Actual active users**: The backend database only knows about different user IDs

### Symptoms
- Bridge health endpoint returns `{"status":"ok","clients":1,"clientInfo":{"1":{"connected":true,"liveState":"CONNECTED","lastSeen":null,"sessionExists":true,"initializing":false}},"restoreRunning":false}`
- Chat retrieval fails with timeout error
- Bridge logs show attempts to restore clients that don't exist in the backend
- Bridge tries to reconnect the same client repeatedly

### Example Scenario
```
Bridge persisted state: User 3 (stale)
Backend active users: User 1 (actual)
Result: Bridge tries to restore client 3, but backend only knows about user 1
```

## Solutions

### 1. Immediate Fix (Manual)
Ask the bridge to reconcile its persisted state against the backend:
```bash
curl -X POST http://localhost:3000/cleanup-stale-state
```

This will:
- Fetch the active (non-suspended) user ids from the backend
- Drop client states in `client_states.json` that no active user owns
- Remove the corresponding stale session directories

If the backend is unreachable the bridge refuses to wipe anything, so make sure
the API is up first (`curl http://localhost:9876/health`).

### 2. Automatic Prevention
The bridge validates its persisted state during restoration, so a normal restart
is usually enough:

- `validateAndCleanupPersistedState()` - validates persisted state against active users
- `POST /cleanup-stale-state` - manual cleanup trigger
- `restoreAllClients()` - runs the same validation before re-opening sockets

### 3. Verifying the Fix
```bash
curl http://localhost:3000/health    # client ids should match active users
curl http://localhost:3000/chats/1   # should return chats, not a timeout
```

## Prevention Strategies

### 1. Regular State Validation
The bridge now automatically validates its persisted state against the backend during restoration.

### 2. User Suspension Handling
When users are suspended in the backend, the bridge automatically:
- Detects suspended users
- Cleans up their client state
- Removes their sessions

### 3. Monitoring
Monitor bridge logs for these indicators:
- `"Found X active users: [user_ids]"`
- `"Validating persisted state against active users..."`
- `"Found X stale client states: [user_ids]"`

## Debugging Commands

### Check Bridge Health
```bash
curl http://localhost:3000/health
```

### Check Client Status
```bash
curl http://localhost:3000/status/1
```

### Manual Cleanup
```bash
curl -X POST http://localhost:3000/cleanup-stale-state
```

### Force Restoration
```bash
curl -X POST http://localhost:3000/restore-all
```

### Test Chat Retrieval
```bash
curl http://localhost:3000/chats/1
```

## File Locations

### Bridge State Files
- **Client states**: `${WHATSAPP_SESSION_PATH}/client_states.json` (i.e. `whatsapp_sessions/client_states.json`)
- **Baileys credentials**: `whatsapp_sessions/session-{user_id}/` (written by `useMultiFileAuthState`)

Baileys keeps no browser cache — there is no `.wwebjs_cache/` to clear.

### Log Files
- **Bridge logs**: `logs/bridge.log`
- **Application logs**: `logs/app.log`
- **Error logs**: `logs/errors.log`

## Recovery Steps

1. **Make sure the backend is up**: `curl http://localhost:9876/health`
2. **Clean up stale state**: `curl -X POST http://localhost:3000/cleanup-stale-state`
3. **Re-restore**: `curl -X POST http://localhost:3000/restore-all`
4. **Test connectivity**: `curl http://localhost:3000/chats/{user_id}`
5. **Monitor logs** (`logs/bridge.log`) for successful restoration

## Common Issues

### Issue: Bridge won't start after cleanup
**Solution**: Check if session directories exist and have proper permissions

### Issue: Users need to re-authenticate
**Solution**: This is expected after clearing stale sessions. Users will need to scan QR codes again.

### Issue: `/cleanup-stale-state` reports it cleaned nothing
**Solution**: The bridge only removes state for user ids the backend does not
list as active. If the backend is unreachable or returns an empty user list, the
bridge deliberately keeps everything. Fix backend connectivity and retry.

## Future Improvements

1. **Periodic validation**: Add scheduled state validation
2. **Better error handling**: More specific error messages for different failure modes
3. **State synchronization**: Real-time sync between backend and bridge state
4. **Monitoring alerts**: Alert when state mismatches are detected

## Support

If issues persist after following this guide:
1. Check the bridge logs for specific error messages
2. Verify backend connectivity and user data
3. Ensure proper file permissions
4. Consider restarting the entire system
