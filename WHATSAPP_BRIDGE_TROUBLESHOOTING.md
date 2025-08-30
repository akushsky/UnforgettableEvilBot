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
Run the bridge state cleanup script:
```bash
python fix_bridge_state.py
```

This script will:
- Clear stale client states from `client_states.json`
- Remove stale session directories
- Clear bridge cache
- Create a backup of the original state

### 2. Automatic Prevention (Code Changes)
The bridge code has been updated to automatically detect and clean up stale state during restoration:

- **New function**: `validateAndCleanupPersistedState()` - validates persisted state against active users
- **New endpoint**: `POST /cleanup-stale-state` - manual cleanup trigger
- **Enhanced restoration**: Automatic cleanup during `restoreAllClients()`

### 3. Testing the Fix
Run the test script to verify the fix:
```bash
python test_bridge_fix.py
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
- **Client states**: `whatsapp_bridge/client_states.json`
- **Session directories**: `whatsapp_sessions/session-{user_id}/`
- **Bridge cache**: `whatsapp_bridge/.wwebjs_cache/`

### Log Files
- **Bridge logs**: `logs/bridge.log`
- **Application logs**: `logs/app.log`
- **Error logs**: `logs/errors.log`

## Recovery Steps

1. **Stop the bridge** (if running)
2. **Run cleanup script**: `python fix_bridge_state.py`
3. **Restart the bridge**
4. **Test connectivity**: `python test_bridge_fix.py`
5. **Monitor logs** for successful restoration

## Common Issues

### Issue: Bridge won't start after cleanup
**Solution**: Check if session directories exist and have proper permissions

### Issue: Users need to re-authenticate
**Solution**: This is expected after clearing stale sessions. Users will need to scan QR codes again.

### Issue: Cleanup script fails
**Solution**: Check file permissions and ensure bridge is stopped before running cleanup.

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
