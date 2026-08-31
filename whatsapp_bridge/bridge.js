/* eslint-disable no-console */
// Baileys 6.7.x is ESM-only; load dynamically from CommonJS
let __baileys = null;
async function getBaileys() {
  if (!__baileys) {
    __baileys = await import('@whiskeysockets/baileys');
  }
  return __baileys;
}
const QRCode = require('qrcode');
const express = require('express');
const cors = require('cors');
const fs = require('fs').promises;
const fssync = require('fs');
const path = require('path');
const axios = require('axios');
const { Boom } = require('@hapi/boom');
const pino = require('pino');

const INIT_TIMEOUT_MS = parseInt(process.env.INIT_TIMEOUT_MS || '45000', 10);
const MAX_INIT_RETRIES = parseInt(process.env.MAX_INIT_RETRIES || '2', 10);
const RESTORE_DELAY_MS = parseInt(process.env.RESTORE_DELAY_MS || '8000', 10);
// When disabled, the supervisor (docker/start.sh) triggers /restore-all once the API is up.
const RESTORE_ON_START = !['0', 'false', 'no', 'off'].includes(
  String(process.env.RESTORE_ON_START ?? '1').trim().toLowerCase()
);
const MESSAGE_POST_ATTEMPTS = parseInt(process.env.MESSAGE_POST_ATTEMPTS || '3', 10);
const MESSAGE_POST_BACKOFF_MS = parseInt(process.env.MESSAGE_POST_BACKOFF_MS || '1000', 10);
// Cap unauthenticated QR/pairing sockets so WhatsApp anti-abuse does not throttle the phone.
const MAX_PAIRING_QR_SESSIONS = parseInt(process.env.MAX_PAIRING_QR_SESSIONS || '3', 10);
const RECONNECT_BASE_MS = parseInt(process.env.RECONNECT_BASE_MS || '30000', 10);
const RECONNECT_MAX_MS = parseInt(process.env.RECONNECT_MAX_MS || String(10 * 60 * 1000), 10);
// Real Chrome identity — custom "WhatsApp Bridge" strings stand out in WA anti-abuse.
const BAILEYS_BROWSER = ['Chrome (Linux)', 'Chrome', '124.0.0.0'];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Digits-only E.164 without leading +. */
function normalizePhoneNumber(phone) {
  return String(phone || '').replace(/\D/g, '');
}

/** Text carried by a message, including media captions. */
function extractMessageContent(message) {
  const payload = message?.message || {};
  const inner = payload.ephemeralMessage?.message || payload.viewOnceMessage?.message
    || payload.viewOnceMessageV2?.message || payload.documentWithCaptionMessage?.message || null;

  return (
    payload.conversation
    || payload.extendedTextMessage?.text
    || payload.imageMessage?.caption
    || payload.videoMessage?.caption
    || payload.documentMessage?.caption
    || (inner ? extractMessageContent({ message: inner }) : '')
    || ''
  );
}

class BaileysWhatsAppBridge {
  constructor() {
    this.clients = new Map();           // userId -> WASocket
    this.clientStates = new Map();      // userId -> state info
    this.qrCodes = new Map();           // userId -> qr string
    this.pairingCodes = new Map();      // userId -> { code, phone, timestamp }
    this.reconnectTimeouts = new Map(); // userId -> timeout
    this.reconnectAttempts = new Map(); // userId -> consecutive session reconnect count
    this.pairingQrSessions = new Map(); // userId -> QR/pairing sockets opened since last explicit start
    this.initializing = new Map();      // userId -> Promise
    this.restorePromise = null;         // de-dupe restore-all
    this.restoreScheduled = false;
    this.persistentChats = new Map();   // userId -> cached chats (survives reconnections)
    this.stores = new Map();            // userId -> in-memory store bound to events
    this.storePersistIntervals = new Map(); // userId -> interval handle

    this.app = express();
    this.pythonBackendUrl = process.env.PYTHON_BACKEND_URL || 'http://127.0.0.1:9876';
    this.webhookSecret = process.env.BRIDGE_WEBHOOK_SECRET || '';
    if (!this.webhookSecret) {
      console.warn('BRIDGE_WEBHOOK_SECRET is not set - backend webhooks will be rejected unless the backend runs in DEBUG mode');
    }
    // Latched once the backend rejects our secret: retrying cannot fix a
    // misconfigured shared secret, it only burns messages against a 401.
    this.bridgeAuthFailed = false;

    this.sessionsRoot = path.resolve(process.env.WHATSAPP_SESSION_PATH || './sessions');
    console.log(`Baileys WhatsApp Bridge sessions root: ${this.sessionsRoot}`);
    if (!fssync.existsSync(this.sessionsRoot)) {
      console.log(`Creating sessions directory: ${this.sessionsRoot}`);
      fssync.mkdirSync(this.sessionsRoot, { recursive: true });
    }

    // Keep the state file next to the sessions so it lives on the same persistent volume.
    this.stateFile = path.join(this.sessionsRoot, 'client_states.json');
    this.migrateLegacyStateFile();

    // Log environment info for debugging
    console.log('Environment info:');
    console.log('- Node.js version:', process.version);
    console.log('- Platform:', process.platform);
    console.log('- Architecture:', process.arch);

    this.setupExpress();
    this.loadPersistedStates().catch(() => {});
    this.startAutoReconnect();
  }

  /** Headers for every call to the Python backend webhooks. */
  backendHeaders(extra = {}) {
    const headers = { 'User-Agent': 'WhatsApp-Bridge/1.0', ...extra };
    if (this.webhookSecret) {
      headers['X-Bridge-Secret'] = this.webhookSecret;
    }
    return headers;
  }

  /* -------------------------- Express routes -------------------------- */

  setupExpress() {
    this.app.use(cors());
    this.app.use(express.json());

    this.app.get('/health', async (_req, res) => {
      const clientInfo = {};
      for (const [userId, client] of this.clients) {
        const state = this.clientStates.get(userId) || {};
        let liveState = null;
        try {
          liveState = client.user ? 'CONNECTED' : 'DISCONNECTED';
        } catch (_) {}
        clientInfo[userId] = {
          connected: liveState === 'CONNECTED',
          liveState,
          lastSeen: state.lastSeen || null,
          sessionExists: await this.checkSessionExists(userId),
          initializing: this.initializing.has(userId),
        };
      }
      const body = { clients: this.clients.size, clientInfo, restoreRunning: !!this.restorePromise };

      if (this.bridgeAuthFailed) {
        // Sessions may look fine while every inbound message is being dropped,
        // so the bridge must not report itself healthy.
        return res.status(503).json({
          status: 'unhealthy',
          error: 'bridge_auth_failed',
          message: 'Backend rejected X-Bridge-Secret - BRIDGE_WEBHOOK_SECRET is misconfigured; message forwarding is disabled',
          ...body,
        });
      }

      res.json({ status: 'ok', ...body });
    });

    this.app.post('/initialize/:userId', async (req, res) => {
      try {
        const userId = req.params.userId;
        // Explicit admin/API pairing start: allow a fresh budget of QR sockets.
        this.resetPairingBudget(userId);
        const result = await this.initializeClientWithReconnect(userId, { preferExistingSession: true });
        res.json(result);
      } catch (error) {
        console.error(`Error initializing client ${req.params.userId}:`, error);
        res.status(500).json({ error: error.message });
      }
    });

    this.app.post('/pair-code/:userId', async (req, res) => {
      try {
        const userId = req.params.userId;
        const phone = normalizePhoneNumber(req.body?.phone);
        if (!phone || phone.length < 8) {
          return res.status(400).json({ error: 'phone is required (E.164 digits, min 8)' });
        }
        this.resetPairingBudget(userId);
        const result = await this.requestPairingCode(userId, phone);
        res.json(result);
      } catch (error) {
        console.error(`Error requesting pairing code for ${req.params.userId}:`, error);
        res.status(500).json({ error: error.message });
      }
    });

    this.app.get('/pair-code/:userId', async (req, res) => {
      const stored = this.pairingCodes.get(req.params.userId);
      if (!stored) return res.status(404).json({ error: 'Pairing code not available' });
      res.json({ success: true, ...stored });
    });

    this.app.post('/cleanup/:userId', async (req, res) => {
      try {
        const result = await this.cleanupClient(req.params.userId);
        res.json(result);
      } catch (error) {
        console.error(`Error cleaning up client ${req.params.userId}:`, error);
        res.status(500).json({ error: error.message });
      }
    });

    this.app.post('/restart/:userId', async (req, res) => {
      try {
        const userId = req.params.userId;
        await this.cleanupClient(userId);
        await new Promise((r) => setTimeout(r, 1200));
        const result = await this.initializeClientWithReconnect(userId, { preferExistingSession: true });
        res.json({ message: 'Client restarted successfully', ...result });
      } catch (error) {
        console.error(`Error restarting client ${req.params.userId}:`, error);
        res.status(500).json({ error: error.message });
      }
    });

    this.app.post('/restore-all', async (_req, res) => {
      try {
        const results = await this.restoreAllClients();
        res.json({ message: 'Restoration initiated', results });
      } catch (error) {
        res.status(500).json({ error: error.message });
      }
    });

    this.app.post('/cleanup-stale-state', async (_req, res) => {
      try {
        console.log('Manual cleanup of stale state requested');

        // Get active users from backend
        let activeUserIds = [];
        try {
          const response = await axios.get(`${this.pythonBackendUrl}/webhook/whatsapp/active-users`, {
            timeout: 10000,
            headers: this.backendHeaders()
          });
          if (response.status === 200) {
            activeUserIds = response.data.active_users.map(user => user.id.toString());
            console.log(`Found ${activeUserIds.length} active users: ${activeUserIds.join(', ')}`);
          }
        } catch (error) {
          console.error('Failed to get active users for manual cleanup:', error.message);
          return res.status(500).json({ error: 'Failed to get active users from backend' });
        }

        const outcome = await this.validateAndCleanupPersistedState(activeUserIds);
        if (outcome && outcome.skipped) {
          return res.json({
            message: 'Stale state cleanup skipped - backend reported no active users',
            skipped: true,
            reason: outcome.reason,
            activeUsers: activeUserIds
          });
        }
        res.json({ message: 'Stale state cleanup completed', activeUsers: activeUserIds });
      } catch (error) {
        console.error('Error during manual cleanup:', error);
        res.status(500).json({ error: error.message });
      }
    });

    this.app.post('/disconnect/:userId', async (req, res) => {
      try {
        const userId = req.params.userId;
        const reason = req.body?.reason || 'admin_request';
        const result = await this.disconnectUser(userId, reason);

        if (result.success) {
          res.json(result);
        } else {
          res.status(400).json(result);
        }
      } catch (error) {
        console.error(`Error disconnecting user ${req.params.userId}:`, error);
        res.status(500).json({ error: error.message });
      }
    });

    this.app.post('/reconnect/:userId', async (req, res) => {
      try {
        const userId = req.params.userId;
        const reason = req.body?.reason || 'admin_request';
        this.resetPairingBudget(userId);
        const result = await this.reconnectUser(userId, reason);

        if (result.success) {
          res.json(result);
        } else {
          res.status(400).json(result);
        }
      } catch (error) {
        console.error(`Error reconnecting user ${req.params.userId}:`, error);
        res.status(500).json({ error: error.message });
      }
    });

    this.app.get('/status/:userId', async (req, res) => {
      const userId = req.params.userId;
      const hasSession = await this.hasRegisteredSession(userId);
      let client = this.clients.get(userId);

      if (!client && hasSession && !this.initializing.has(userId)) {
        // lazy-kick start (non-blocking) — only for completed pairings
        this.initializeClientWithReconnect(userId, { preferExistingSession: true })
          .catch((e) => console.error(`Lazy init failed for ${userId}:`, e));
      }

      const snap = this.clientStates.get(userId) || {};
      let info = null, liveState = null, connected = false;
      if (client) {
        info = client.user ? { id: client.user.id, name: client.user.name } : null;
        try {
          liveState = client.user ? 'CONNECTED' : 'DISCONNECTED';
        } catch (_) {}
        connected = liveState === 'CONNECTED';
      }

      res.json({
        connected,
        info,
        state: liveState,
        lastSeen: snap.lastSeen || null,
        hasSession,
        initializing: this.initializing.has(userId),
        sessionPath: this.sessionFolderFor(userId),
        awaitingPairing: !!snap.awaitingPairing,
        pairingStopped: !!snap.pairingStopped,
        disconnectStatusCode: snap.disconnectStatusCode || null,
        disconnectReason: snap.disconnectReason || null,
      });
    });

    this.app.get('/chats/:userId', async (req, res) => {
      const userId = req.params.userId;
      let client = this.clients.get(userId);

      if (!client) {
        const has = await this.checkSessionExists(userId);
        if (!has) return res.status(404).json({ error: 'Client not found', chats: [] });
        // Start client (do not wait for full ready)
        await this.ensureClientStarted(userId);
        client = this.clients.get(userId);
      }

      try {
        const ready = await this.waitForClientReady(client, userId, 60000);
        if (!ready) {
          return res.status(400).json({ error: 'Client not ready after timeout', chats: [] });
        }
        const chats = await this.getChatsSafe(client, userId, { totalTimeoutMs: 45000, liteFirst: true });
        return res.json({ chats });
      } catch (err) {
        console.error(`Error getting chats for user ${userId}:`, err);
        return res.status(500).json({ error: String(err.message || err), chats: [] });
      }
    });

    this.app.get('/qr/:userId', async (req, res) => {
      try {
        const qrData = this.qrCodes.get(req.params.userId);
        if (!qrData) return res.status(404).json({ error: 'QR code not available' });

        const qrImage = await QRCode.toDataURL(qrData, {
          errorCorrectionLevel: 'M',
          type: 'image/png',
          width: 256,
        });
        res.json({ success: true, qrCode: qrImage, timestamp: new Date().toISOString() });
      } catch (error) {
        res.status(500).json({ error: error.message });
      }
    });


  }

  /* ----------------------------- Utilities ----------------------------- */

  withTimeout(promise, ms, tag = 'operation') {
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error(`${tag} timed out after ${ms}ms`)), ms);
      promise.then((v) => { clearTimeout(t); resolve(v); }, (e) => { clearTimeout(t); reject(e); });
    });
  }

  sessionFolderFor(userId) {
    return path.join(this.sessionsRoot, `session-${userId}`);
  }

  chatCacheFileFor(userId) {
    return path.join(this.sessionFolderFor(userId), 'chats.json');
  }

  /** Reset QR/pairing attempt budget after an explicit admin pairing request. */
  resetPairingBudget(userId) {
    this.pairingQrSessions.set(userId, 0);
    this.reconnectAttempts.delete(userId);
    this.updateClientState(userId, {
      awaitingPairing: false,
      pairingStopped: false,
      pairingStopReason: null,
    });
  }

  /**
   * True only when Baileys creds show a completed phone pairing (registered + me).
   * An empty or half-written session folder from a QR attempt must not count.
   */
  async hasRegisteredSession(userId) {
    try {
      const credsPath = path.join(this.sessionFolderFor(userId), 'creds.json');
      const raw = await fs.readFile(credsPath, 'utf8');
      const creds = JSON.parse(raw);
      return !!(creds && creds.registered && creds.me);
    } catch {
      return false;
    }
  }

  reconnectDelayMs(userId) {
    const attempt = this.reconnectAttempts.get(userId) || 0;
    const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * Math.pow(2, attempt));
    return delay;
  }

  scheduleSessionReconnect(userId) {
    const old = this.reconnectTimeouts.get(userId);
    if (old) clearTimeout(old);
    const delay = this.reconnectDelayMs(userId);
    const attempt = (this.reconnectAttempts.get(userId) || 0) + 1;
    this.reconnectAttempts.set(userId, attempt);
    console.log(`schedule reconnect ${userId} in ${delay}ms (attempt ${attempt})`);
    const t = setTimeout(() => this.attemptReconnect(userId), delay);
    this.reconnectTimeouts.set(userId, t);
  }

  /**
   * Start a fresh Baileys socket and request a phone pairing code
   * (WhatsApp "Link with phone number" flow).
   */
  async requestPairingCode(userId, phone) {
    const digits = normalizePhoneNumber(phone);
    if (!digits || digits.length < 8) {
      throw new Error('Invalid phone number');
    }

    // Fresh session required — registered creds would skip pairing.
    // initializeClientWithReconnect owns the pairing-budget counter.
    const initResult = await this.initializeClientWithReconnect(userId, { preferExistingSession: false });
    if (initResult?.pairingStopped) {
      throw new Error(initResult.message || 'Pairing stopped');
    }

    const client = this.clients.get(userId);
    if (!client || typeof client.requestPairingCode !== 'function') {
      throw new Error('Baileys client does not support requestPairingCode');
    }

    // Give the socket a moment to open the websocket before requesting the code.
    await sleep(1500);
    const code = await client.requestPairingCode(digits);
    const payload = {
      code,
      phone: digits,
      timestamp: new Date().toISOString(),
      userId,
    };
    this.pairingCodes.set(userId, payload);
    this.updateClientState(userId, {
      awaitingPairing: true,
      pairingStopped: false,
      pairingMethod: 'phone',
    });
    console.log(`Pairing code for ${userId} (phone …${digits.slice(-4)}): ${code}`);
    return { success: true, ...payload };
  }

  async listLocalSessionUserIds() {
    const dirs = await fs.readdir(this.sessionsRoot).catch(() => []);
    const ids = [];
    for (const d of dirs) {
      if (d.startsWith('session-')) ids.push(d.replace(/^session-/, ''));
    }
    return ids;
  }

  inferChatKindFromWid(wid) {
    if (!wid) return 'unknown';
    const server = wid.includes('@') ? wid.split('@')[1] : '';
    switch (server) {
      case 'g.us': return 'group';
      case 'broadcast': return 'broadcast';
      case 'newsletter': return 'newsletter';
      case 'c.us':
      case 'l.us': return 'private';
      default: return server || 'unknown';
    }
  }

  inferIsGroupFromWid(wid) {
    return this.inferChatKindFromWid(wid) === 'group';
  }

  normalizeChat(chatId, source = {}) {
    if (!chatId) return null;
    const isGroup = this.inferIsGroupFromWid(chatId) || String(chatId).endsWith('@g.us');
    const name = source.name || source.subject || source.pushName || (typeof chatId === 'string' ? chatId.split('@')[0] : 'Unknown') || 'Unknown';
    let participants = 0;
    if (Array.isArray(source.participants)) participants = source.participants.length;
    else if (source.size) participants = source.size;
    else if (source.participants && typeof source.participants === 'object') participants = Object.keys(source.participants).length;

    return {
      id: chatId,
      name,
      isGroup,
      participants,
      lastMessage: null,
    };
  }

  mergeChats(existingList, incomingList) {
    const byId = new Map();
    for (const c of existingList) byId.set(c.id, c);
    for (const c of incomingList) {
      if (!c || !c.id) continue;
      const prev = byId.get(c.id);
      if (!prev) byId.set(c.id, c);
      else {
        byId.set(c.id, {
          ...prev,
          ...c,
          name: c.name && c.name !== 'Unknown' ? c.name : prev.name,
          participants: typeof c.participants === 'number' && c.participants > 0 ? c.participants : prev.participants,
        });
      }
    }
    return Array.from(byId.values());
  }

  async savePersistentChats(userId) {
    try {
      const file = this.chatCacheFileFor(userId);
      const folder = this.sessionFolderFor(userId);
      if (!fssync.existsSync(folder)) fssync.mkdirSync(folder, { recursive: true });
      const data = this.persistentChats.get(userId) || [];
      await fs.writeFile(file, JSON.stringify(data, null, 2));
    } catch (e) {
      console.error(`savePersistentChats failed ${userId}:`, e?.message || e);
    }
  }

  async loadPersistentChats(userId) {
    try {
      const file = this.chatCacheFileFor(userId);
      const raw = await fs.readFile(file, 'utf8');
      const data = JSON.parse(raw);
      if (Array.isArray(data) && data.length) {
        this.persistentChats.set(userId, data);
        console.log(`Loaded ${data.length} cached chats for ${userId}`);
        return data;
      }
    } catch (_) {}
    return [];
  }

  /* ----------------------- Lifecycle / initialization ----------------------- */

  async ensureClientStarted(userId) {
    if (this.clients.get(userId)) return;
    // A concurrent caller is already starting this client - wait for it rather
    // than returning to a caller that will immediately find no client.
    const pending = this.initializing.get(userId);
    if (pending) {
      await pending.catch((e) => console.error(`ensureClientStarted: pending init failed for ${userId}:`, e?.message || e));
      return;
    }
    try {
      await this.initializeClientWithReconnect(userId, { preferExistingSession: true });
    }
    catch (e) {
      console.error(`ensureClientStarted failed for ${userId}:`, e.message);
    }
  }

  async initializeClientWithReconnect(userId, { preferExistingSession = true } = {}) {
    if (this.initializing.has(userId)) {
      console.log(`[init] dedupe: already initializing ${userId}`);
      return this.initializing.get(userId);
    }

    const run = (async () => {
      const existing = this.clients.get(userId);
      if (existing) {
        try {
          const snap = this.clientStates.get(userId) || {};
          if (existing.user && snap.connected === true) {
            return { message: 'Client already connected', userId, connected: true };
          }
          // Recycle stale client (preserve session on disk)
          try { existing.end(); } catch (_) {}
          this.clients.delete(userId);
        } catch (_) {}
      }

      let hasSession = false;
      if (preferExistingSession) {
        hasSession = await this.hasRegisteredSession(userId);
        if (!hasSession) {
          // Folder may exist from a previous unfinished QR attempt — not a real session.
          hasSession = false;
        }
      } else {
        // A fresh pairing was requested: the old credentials must go, otherwise
        // useMultiFileAuthState reuses them and no QR is ever emitted.
        console.log(`Wiping session for ${userId} - fresh pairing requested`);
        try {
          await fs.rm(this.sessionFolderFor(userId), { recursive: true, force: true });
        } catch (e) {
          // Continuing would hand the stale creds back to useMultiFileAuthState:
          // no QR is emitted and the caller waits on a pairing that never comes.
          console.error(`[init] session wipe failed for ${userId}:`, e?.message || e);
          throw new Error(`Session wipe failed for ${userId} - aborting fresh pairing: ${e?.message || e}`);
        }
        this.persistentChats.delete(userId);
        this.qrCodes.delete(userId);
        this.pairingCodes.delete(userId);
      }

      // Unauthenticated init burns a pairing attempt. Cap them so WhatsApp
      // does not throttle the phone account for "link new device" spam.
      if (!hasSession) {
        const used = this.pairingQrSessions.get(userId) || 0;
        if (used >= MAX_PAIRING_QR_SESSIONS) {
          console.warn(
            `[init] pairing budget exhausted for ${userId} (${used}/${MAX_PAIRING_QR_SESSIONS}) - refusing new QR socket`
          );
          this.updateClientState(userId, {
            awaitingPairing: true,
            pairingStopped: true,
            pairingStopReason: `pairing budget exhausted (${MAX_PAIRING_QR_SESSIONS})`,
            connected: false,
          });
          return {
            message: 'Pairing stopped - too many QR sessions without successful link',
            userId,
            hasSession: false,
            pairingStopped: true,
          };
        }
        this.pairingQrSessions.set(userId, used + 1);
        console.log(`[init] pairing socket ${used + 1}/${MAX_PAIRING_QR_SESSIONS} for ${userId}`);
      }

      console.log(`Initializing Baileys client for ${userId} (hasSession=${hasSession})`);

      let lastError = null;
      for (let attempt = 1; attempt <= Math.max(1, MAX_INIT_RETRIES); attempt++) {
        try {
          const sessionPath = this.sessionFolderFor(userId);
          const B = await getBaileys();
          const { state, saveCreds } = await B.useMultiFileAuthState(sessionPath);

          const { version, isLatest } = await B.fetchLatestBaileysVersion();
          console.log(`Using WA v${version.join('.')}, isLatest: ${isLatest}`);

          const client = B.default({
            version,
            logger: pino({ level: 'silent' }),
            printQRInTerminal: false,
            auth: {
              creds: state.creds,
              keys: B.makeCacheableSignalKeyStore(state.keys, pino({ level: 'fatal' }).child({ level: 'fatal' })),
            },
            browser: BAILEYS_BROWSER,
            connectTimeoutMs: INIT_TIMEOUT_MS,
            defaultQueryTimeoutMs: 60000,
            emitOwnEvents: false,
            generateHighQualityLinkPreview: true,
            // No outgoing message store here: returning a fabricated body would
            // make Baileys re-send bogus content on retry requests.
            getMessage: async () => undefined,
          });

          // attach handlers once per attempt
          await this.setupClientHandlers(client, userId, saveCreds, sessionPath);
          this.clients.set(userId, client);
          this.updateClientState(userId, {
            hasSession,
            lastInitialized: new Date().toISOString(),
            connected: false,
            awaitingPairing: !hasSession,
            pairingStopped: false,
          });

          // Wait for connection or QR
          await this.withTimeout(
            new Promise((resolve, reject) => {
              const timeout = setTimeout(() => reject(new Error('Connection timeout')), INIT_TIMEOUT_MS);

              const onReady = () => {
                clearTimeout(timeout);
                resolve();
              };

              const onQR = (qr) => {
                clearTimeout(timeout);
                this.qrCodes.set(userId, qr);
                resolve(); // QR is also a valid state
              };

              // Check if already connected
              if (client.user) {
                onReady();
              } else {
                // Listen for events
                client.ev.on('connection.update', (update) => {
                  if (update.connection === 'open') {
                    onReady();
                  } else if (update.qr) {
                    onQR(update.qr);
                  }
                });
              }
            }),
            INIT_TIMEOUT_MS,
            `client.initialize(${userId})`
          );

          return { message: 'Client initialization started', userId, hasSession };
        } catch (err) {
          lastError = err;
          console.error(`[init] attempt ${attempt} failed for ${userId}:`, err?.message || err);

          // Clean up failed client
          const client = this.clients.get(userId);
          if (client) {
            try {
              client.end();
            } catch (_) {}
            this.clients.delete(userId);
          }

          // Optionally wipe bad session and retry clean
          const shouldWipe = process.env.WIPE_BAD_SESSIONS === '1' && hasSession;
          if (shouldWipe) {
            console.warn(`[init] wiping session for ${userId} and retrying…`);
            try {
              await fs.rm(this.sessionFolderFor(userId), { recursive: true, force: true });
            }
            catch (e) {
              console.error(`[init] wipe failed for ${userId}:`, e?.message || e);
            }
          }

          if (attempt < Math.max(1, MAX_INIT_RETRIES)) {
            await new Promise((r) => setTimeout(r, 1500));
            continue;
          }
        }
      }

      throw lastError || new Error('initialize failed');
    })();

    this.initializing.set(userId, run);
    try { return await run; }
    finally { this.initializing.delete(userId); }
  }

  async setupClientHandlers(client, userId, saveCreds, sessionPath) {
    // Baileys 6.7.19 no longer provides makeInMemoryStore; skip store binding

    // Load cached chats from disk into memory cache (best-effort)
    await this.loadPersistentChats(userId).catch(() => {});

    client.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        console.log(`QR for ${userId}`);
        this.qrCodes.set(userId, qr);
      }

      if (connection === 'open') {
        console.log(`connected ${userId}`);
        this.pairingQrSessions.set(userId, 0);
        this.reconnectAttempts.delete(userId);
        this.pairingCodes.delete(userId);
        this.updateClientState(userId, {
          connected: true,
          lastSeen: new Date().toISOString(),
          hasSession: true,
          awaitingPairing: false,
          pairingStopped: false,
          pairingStopReason: null,
          disconnectStatusCode: null,
        });

        // Notify backend
        axios.post(`${this.pythonBackendUrl}/webhook/whatsapp/connected`, {
          userId,
          timestamp: new Date().toISOString(),
          clientInfo: client.user || { connected: true },
        }, { headers: this.backendHeaders() }).catch((err) => console.error(`notify backend failed ${userId}:`, err));

        this.qrCodes.delete(userId);

        // Proactively refresh group list on connect; private chats will build over time
        try {
          const groups = await client.groupFetchAllParticipating().catch(() => null);
          if (groups) {
            const groupArray = Object.values(groups);
            const processed = groupArray.map(g => ({
              id: g.id,
              name: g.subject || g.id.split('@')[0] || 'Group',
              isGroup: true,
              participants: Array.isArray(g.participants) ? g.participants.length : (g.size || 0),
              lastMessage: null,
            }));
            this.persistentChats.set(userId, this.mergeChats(this.persistentChats.get(userId) || [], processed));
            await this.savePersistentChats(userId).catch(() => {});
          }
        } catch (e) {
          console.error(`group refresh failed ${userId}:`, e?.message || e);
        }
      }

      if (connection === 'close') {
        const B = await getBaileys();
        const statusCode = lastDisconnect?.error instanceof Boom
          ? lastDisconnect.error.output?.statusCode
          : null;
        const loggedOut = statusCode === B.DisconnectReason.loggedOut;
        const reasonMsg = lastDisconnect?.error?.message || 'unknown';
        const registered = await this.hasRegisteredSession(userId);

        console.log(
          `connection closed for ${userId} statusCode=${statusCode} reason=${reasonMsg} `
          + `registered=${registered} loggedOut=${loggedOut}`
        );

        this.updateClientState(userId, {
          connected: false,
          lastDisconnected: new Date().toISOString(),
          disconnectReason: reasonMsg,
          disconnectStatusCode: statusCode,
        });

        // Mirror of the /connected notification so the backend does not keep
        // reporting a dead session as connected.
        axios.post(`${this.pythonBackendUrl}/webhook/whatsapp/disconnected`, {
          userId,
          timestamp: new Date().toISOString(),
          clientInfo: {
            connected: false,
            loggedOut,
            reason: reasonMsg,
            statusCode,
          },
        }, { headers: this.backendHeaders() }).catch((err) => console.error(`notify backend disconnect failed ${userId}:`, err?.message || err));

        this.qrCodes.delete(userId);

        // Never auto-spin new QR sockets for an unpaired account — that is what
        // burned WhatsApp's link-device anti-abuse for user 2 (~186 cycles).
        if (loggedOut) {
          console.log(`logged out ${userId} - not reconnecting`);
          this.updateClientState(userId, { awaitingPairing: false, hasSession: false });
          return;
        }

        if (!registered) {
          const used = this.pairingQrSessions.get(userId) || 0;
          const stopped = used >= MAX_PAIRING_QR_SESSIONS;
          console.log(
            `pairing close for ${userId}: no registered session `
            + `(${used}/${MAX_PAIRING_QR_SESSIONS}) - ${stopped ? 'STOP' : 'awaiting explicit re-init'}`
          );
          this.updateClientState(userId, {
            awaitingPairing: true,
            pairingStopped: stopped,
            pairingStopReason: stopped
              ? `pairing budget exhausted (${MAX_PAIRING_QR_SESSIONS})`
              : 'qr session closed without scan',
            hasSession: false,
          });
          // Drop the dead unpaired socket; admin must call /initialize or /pair-code again.
          this.clients.delete(userId);
          return;
        }

        this.scheduleSessionReconnect(userId);
      }
    });

    client.ev.on('creds.update', saveCreds);

    client.ev.on('messages.upsert', async (m) => {
      // A single upsert can carry a batch; taking only [0] silently dropped the rest.
      for (const msg of m.messages || []) {
        if (!msg?.key || msg.key.fromMe || !msg.message) continue;
        console.log(`MESSAGE for ${userId}: ${msg.message.conversation?.substring(0, 50) || 'media'}...`);
        try {
          await this.handleIncomingMessage(userId, msg);
        }
        catch (e) {
          console.error(`handle msg ${userId}:`, e);
        }
      }
    });

    client.ev.on('messages.update', async (updates) => {
      for (const update of updates) {
        if (update.update.status) {
          console.log(`Message status update for ${userId}: ${update.update.status}`);
        }
      }
    });

    client.ev.on('messaging-history.set', ({ chats: newChats, contacts: newContacts, messages: newMessages, syncType }) => {
      console.log(`Messaging history set for ${userId}:`, {
        chatsCount: newChats ? newChats.length : 0,
        contactsCount: newContacts ? newContacts.length : 0,
        messagesCount: newMessages ? newMessages.length : 0,
        syncType
      });

      // Store chats persistently so they survive reconnections
      if (newChats && newChats.length > 0) {
        const processedChats = newChats.map(chat => this.normalizeChat(chat.id || chat.jid || chat, chat)).filter(Boolean);
        const merged = this.mergeChats(this.persistentChats.get(userId) || [], processedChats);
        this.persistentChats.set(userId, merged);
        this.savePersistentChats(userId).catch(() => {});
        console.log(`Persistently stored ${merged.length} chats for user ${userId}`);
      }
    });

    // Keep chat cache updated during lifecycle
    client.ev.on('chats.set', ({ chats, isLatest }) => {
      try {
        const processed = (chats || []).map(c => this.normalizeChat(c.id || c.jid, c)).filter(Boolean);
        const merged = this.mergeChats(this.persistentChats.get(userId) || [], processed);
        this.persistentChats.set(userId, merged);
        this.savePersistentChats(userId).catch(() => {});
        console.log(`chats.set(${isLatest}) updated cache to ${merged.length} for ${userId}`);
      } catch (e) {
        console.error('chats.set handler error:', e?.message || e);
      }
    });

    client.ev.on('chats.upsert', (newChats) => {
      try {
        const processed = (newChats || []).map(c => this.normalizeChat(c.id || c.jid, c)).filter(Boolean);
        const merged = this.mergeChats(this.persistentChats.get(userId) || [], processed);
        this.persistentChats.set(userId, merged);
        this.savePersistentChats(userId).catch(() => {});
        console.log(`chats.upsert added/merged ${processed.length} for ${userId}`);
      } catch (e) { console.error('chats.upsert error:', e?.message || e); }
    });

    client.ev.on('chats.update', (updates) => {
      try {
        const current = this.persistentChats.get(userId) || [];
        for (const upd of updates || []) {
          const id = upd.id || upd.jid;
          if (!id) continue;
          const idx = current.findIndex(c => c.id === id);
          if (idx >= 0) {
            const existing = current[idx];
            current[idx] = {
              ...existing,
              name: upd.name || upd.subject || existing.name,
            };
          }
        }
        this.persistentChats.set(userId, current);
        this.savePersistentChats(userId).catch(() => {});
      } catch (e) { console.error('chats.update error:', e?.message || e); }
    });

    client.ev.on('groups.update', (updates) => {
      try {
        const current = this.persistentChats.get(userId) || [];
        for (const upd of updates || []) {
          const id = upd.id;
          if (!id) continue;
          const idx = current.findIndex(c => c.id === id);
          if (idx >= 0) {
            current[idx] = { ...current[idx], name: upd.subject || current[idx].name, isGroup: true };
          }
        }
        this.persistentChats.set(userId, current);
        this.savePersistentChats(userId).catch(() => {});
      } catch (e) { console.error('groups.update error:', e?.message || e); }
    });

    client.ev.on('group-participants.update', (ev) => {
      try {
        const current = this.persistentChats.get(userId) || [];
        const idx = current.findIndex(c => c.id === ev.id);
        if (idx >= 0) {
          const delta = ev.action === 'add' ? (ev.participants?.length || 0) : ev.action === 'remove' ? -(ev.participants?.length || 0) : 0;
          current[idx] = { ...current[idx], isGroup: true, participants: Math.max(0, (current[idx].participants || 0) + delta) };
          this.persistentChats.set(userId, current);
          this.savePersistentChats(userId).catch(() => {});
        }
      } catch (e) { console.error('group-participants.update error:', e?.message || e); }
    });
  }

  async attemptReconnect(userId) {
    const snap = this.clientStates.get(userId) || {};
    const client = this.clients.get(userId);

    // Never turn a failed pairing into an infinite QR spawn.
    if (!(await this.hasRegisteredSession(userId))) {
      console.log(`reconnect skipped ${userId}: no registered session`);
      this.updateClientState(userId, {
        awaitingPairing: true,
        hasSession: false,
      });
      return;
    }

    if (client) {
      let fullyConnected = false;
      try { fullyConnected = !!(client.user) && snap.connected === true; } catch (_) {}
      if (fullyConnected) {
        this.reconnectAttempts.delete(userId);
        return; // Already connected
      }

      // Recycle stale client (preserve session on disk)
      try { client.end(); } catch (_) {}
      this.clients.delete(userId);
    }

    console.log(`reconnect ${userId}`);
    try {
      await this.initializeClientWithReconnect(userId, { preferExistingSession: true });
    } catch (error) {
      console.error(`reconnect failed ${userId}:`, error?.message || error);
      this.scheduleSessionReconnect(userId);
    }
  }

  startAutoReconnect() {
    setInterval(async () => {
      console.log('periodic health check…');
      for (const [userId, client] of this.clients) {
        const state = this.clientStates.get(userId) || {};
        let live = null;
        try {
          live = client.user ? 'CONNECTED' : 'DISCONNECTED';
        } catch (_) {}
        const ok = live === 'CONNECTED' && state.connected === true;
        const registered = state.hasSession || (await this.hasRegisteredSession(userId));
        if (registered && !ok) {
          console.log(`health says reconnect ${userId} (live=${live})`);
          this.attemptReconnect(userId);
        }
      }
    }, 5 * 60 * 1000);
  }

  /* ----------------------------- Messages ----------------------------- */

  async handleIncomingMessage(userId, message) {
    console.log(`Processing incoming message for ${userId}: ${message.message?.conversation?.substring(0, 50) || 'media'}...`);

    const chatId = message.key.remoteJid;
    const sender = message.key.participant || message.key.remoteJid;
    const content = extractMessageContent(message);
    const timestamp = new Date(message.messageTimestamp * 1000).toISOString();

    // Get chat info
    let chatName = 'Unknown';
    let chatType = 'private';
    let participants = 0;

    try {
      const client = this.clients.get(userId);
      if (client) {
        if (chatId.endsWith('@g.us')) {
          chatType = 'group';
          const groupMetadata = await client.groupMetadata(chatId).catch(() => null);
          if (groupMetadata) {
            chatName = groupMetadata.subject || 'Group';
            participants = groupMetadata.participants?.length || 0;
          }
        } else {
          // No contactsUpsert method exists on Baileys client. Prefer pushName or store contacts if available
          const store = this.stores.get(userId);
          const B = await getBaileys();
          const contactFromStore = store && store.contacts ? (store.contacts[chatId] || store.contacts[B.jidDecode?.(chatId)?.user]) : null;
          chatName = message.pushName || contactFromStore?.name || contactFromStore?.notify || chatId.split('@')[0] || 'Unknown';
        }
      }
    } catch (e) {
      console.error(`Error getting chat info for ${userId}:`, e);
    }

    const messageData = {
      userId,
      messageId: message.key.id,
      chatId: chatId,
      chatName: chatName,
      chatType: chatType,
      sender: sender,
      content: content,
      timestamp: timestamp,
      importance: 1, // Default importance - AI analysis will be done on backend
      hasMedia: !!(message.message?.imageMessage || message.message?.videoMessage || message.message?.audioMessage || message.message?.documentMessage),
    };

    const forwarded = await this.postMessageWithRetry(userId, messageData);
    if (!forwarded) {
      await this.recordFailedForward(userId, messageData);
    }

    // Chat-cache maintenance still runs - it is local bookkeeping and must not
    // be skipped just because the backend was unreachable - but the message
    // itself is recorded as lost above rather than treated as delivered.
    try {
      const entry = this.normalizeChat(chatId, { subject: chatName, name: chatName });
      const merged = this.mergeChats(this.persistentChats.get(userId) || [], [entry]);
      this.persistentChats.set(userId, merged);
      await this.savePersistentChats(userId).catch(() => {});
    } catch (_) {}

    return forwarded;
  }

  failedForwardsDir() {
    return path.join(this.sessionsRoot, 'failed_forwards');
  }

  /**
   * Append a message the backend never accepted to a JSONL file on the session
   * volume, so it can be inspected and replayed instead of vanishing.
   */
  async recordFailedForward(userId, messageData, reason = 'forward_failed') {
    const dir = this.failedForwardsDir();
    const file = path.join(dir, `user-${userId}.jsonl`);
    const record = { recordedAt: new Date().toISOString(), reason, userId, message: messageData };

    try {
      if (!fssync.existsSync(dir)) fssync.mkdirSync(dir, { recursive: true });
      await fs.appendFile(file, `${JSON.stringify(record)}\n`);
      console.error(`!!! MESSAGE NOT FORWARDED for ${userId} (${reason}) - saved to ${file} for replay`);
    } catch (e) {
      // Last resort: the payload goes to the log so it is not lost silently.
      console.error(`!!! MESSAGE NOT FORWARDED for ${userId} (${reason}) AND could not be persisted:`, e?.message || e);
      console.error(`!!! unforwarded payload: ${JSON.stringify(record)}`);
    }
  }

  /**
   * Forward a message to the backend, retrying transient failures.
   * Retries on 429 / 5xx and on network errors; 4xx other than 429 are final.
   * HTTP 401 is fatal: the shared secret is wrong, so every later forward is
   * refused immediately instead of hammering the backend.
   */
  async postMessageWithRetry(userId, messageData, attempts = MESSAGE_POST_ATTEMPTS) {
    const url = `${this.pythonBackendUrl}/webhook/whatsapp/message`;

    if (this.bridgeAuthFailed) {
      console.error(`refusing to forward msg for ${userId}: backend rejected X-Bridge-Secret - fix BRIDGE_WEBHOOK_SECRET (must match the API) and restart the bridge`);
      return false;
    }

    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      try {
        await axios.post(url, messageData, { headers: this.backendHeaders(), timeout: 15000 });
        console.log(`forwarded msg ${userId}`);
        return true;
      } catch (error) {
        const status = error?.response?.status;
        const retryable = status === undefined || status === 429 || status >= 500;
        const detail = status ? `HTTP ${status}` : (error?.code || error?.message || 'unknown error');

        if (status === 401) {
          this.bridgeAuthFailed = true;
          console.error(`!!! FATAL: backend rejected X-Bridge-Secret for ${userId} (HTTP 401). BRIDGE_WEBHOOK_SECRET is missing or does not match the API secret. Message forwarding is now disabled and /health reports unhealthy.`);
          return false;
        }

        if (!retryable || attempt === attempts) {
          console.error(`forward msg failed ${userId} (${detail}) after ${attempt} attempt(s)`);
          return false;
        }

        const delay = MESSAGE_POST_BACKOFF_MS * 2 ** (attempt - 1);
        console.warn(`forward msg retry ${attempt}/${attempts - 1} for ${userId} in ${delay}ms (${detail})`);
        await sleep(delay);
      }
    }

    return false;
  }

  /* -------------------- Chats / Store readiness & fetch -------------------- */

  async getChatsSafe(client, userId, { totalTimeoutMs = 45000, liteFirst = true } = {}) {
    const work = (async () => {
      if (!client.user) {
        throw new Error(`Client ${userId} not fully connected`);
      }

      try {
        // First, try to get chats from persistent cache (survives reconnections)
        const persistentChats = this.persistentChats.get(userId);
        if (persistentChats && persistentChats.length > 0) {
          console.log(`Returning ${persistentChats.length} chats from persistent cache for user ${userId}`);
          return persistentChats;
        }

        // Fallback: Get chats from the in-memory store (bound to events)
        const store = this.stores.get(userId);
        let chats = [];
        if (store && store.chats) {
          try {
            const all = typeof store.chats.all === 'function'
              ? store.chats.all()
              : Array.isArray(store.chats)
                ? store.chats
                : (typeof store.chats.values === 'function' ? Array.from(store.chats.values()) : []);
            for (const chat of all) {
              const id = chat.id || chat.jid;
              if (!id || id === 'status@broadcast') continue;
              chats.push(this.normalizeChat(id, chat));
            }
          } catch (e) {
            console.log(`store chats read failed ${userId}:`, e.message);
          }
        }

        console.log(`Returning ${chats.length} chats for user ${userId}`);
        return chats;

      } catch (e) {
        console.log(`getChats failed ${userId}:`, e.message);
        return [];
      }
    })();

    return this.withTimeout(work, totalTimeoutMs, 'getChatsSafe');
  }

  async waitForClientReady(client, userId, timeout = 60000) {
    const start = Date.now();
    const snap = this.clientStates.get(userId) || {};
    if (snap.connected === true) return true;

    return new Promise((resolve) => {
      const interval = setInterval(async () => {
        const internal = this.clientStates.get(userId) || {};
        if (internal.connected === true) {
          clearInterval(interval);
          return resolve(true);
        }
        try {
          if (client.user) {
            clearInterval(interval);
            return resolve(true);
          }
        } catch (_) {}
        if (Date.now() - start > timeout) {
          clearInterval(interval);
          return resolve(false);
        }
      }, 800);
    });
  }

  /* ----------------------------- Persistence ----------------------------- */

  updateClientState(userId, updates) {
    const current = this.clientStates.get(userId) || {};
    const next = { ...current, ...updates };
    this.clientStates.set(userId, next);
    this.saveStatesToFile().catch(console.error);
  }

  async saveStatesToFile() {
    try {
      const states = Object.fromEntries(this.clientStates);
      await fs.writeFile(this.stateFile, JSON.stringify(states, null, 2));
    } catch (error) {
      console.error('save state file error:', error);
    }
  }

  /** Older builds wrote client_states.json into the working directory instead of the volume. */
  migrateLegacyStateFile() {
    const legacy = path.resolve('./client_states.json');
    if (legacy === this.stateFile) return;
    try {
      if (fssync.existsSync(legacy) && !fssync.existsSync(this.stateFile)) {
        fssync.copyFileSync(legacy, this.stateFile);
        console.log(`Migrated legacy state file ${legacy} -> ${this.stateFile}`);
      }
    } catch (error) {
      console.error('Failed to migrate legacy state file:', error.message);
    }
  }

  async loadPersistedStates() {
    try {
      const data = await fs.readFile(this.stateFile, 'utf8');
      const states = JSON.parse(data);
      for (const [userId, state] of Object.entries(states)) {
        this.clientStates.set(userId, state);
      }
      console.log(`Loaded ${Object.keys(states).length} persisted client states`);
      return states;
    } catch {
      console.log('No persisted states found or error loading them');
      return {};
    }
  }

  async checkSessionExists(userId) {
    try {
      const folder = this.sessionFolderFor(userId);
      await fs.access(folder);
      const files = await fs.readdir(folder);
      return Array.isArray(files) && files.length >= 2;
    } catch { return false; }
  }

  /**
   * True only when the backend gave us a usable, non-empty roster of active users.
   * An empty or missing list means "unknown" - never a licence to wipe sessions.
   */
  hasUsableActiveUserList(activeUserIds) {
    return Array.isArray(activeUserIds) && activeUserIds.length > 0;
  }

  async validateAndCleanupPersistedState(activeUserIds) {
    console.log('Validating persisted state against active users...');

    if (!this.hasUsableActiveUserList(activeUserIds)) {
      console.warn(
        'Skipping stale-state cleanup: active user list is empty or unavailable. ' +
        'Refusing to wipe persisted client states without a known-good roster.'
      );
      return { skipped: true, reason: 'empty_active_user_list' };
    }

    // Check for stale client states
    const staleStateUsers = Array.from(this.clientStates.keys()).filter(
      userId => !activeUserIds.includes(userId)
    );

    if (staleStateUsers.length > 0) {
      console.log(`Found ${staleStateUsers.length} stale client states: ${staleStateUsers.join(', ')}`);

      for (const userId of staleStateUsers) {
        console.log(`Cleaning up stale client state for user ${userId}`);
        this.clientStates.delete(userId);

        // Also cleanup any existing client
        const client = this.clients.get(userId);
        if (client) {
          try {
            client.end();
            this.clients.delete(userId);
            console.log(`Destroyed stale client for user ${userId}`);
          } catch (error) {
            console.error(`Failed to destroy stale client for user ${userId}:`, error.message);
          }
        }
      }

      // Save the cleaned state
      await this.saveStatesToFile();
      console.log('Persisted state cleaned and saved');
    } else {
      console.log('No stale client states found');
    }
  }

  /* ------------------------------- Server ------------------------------- */

  async start(port = 3000) {
    this.server = this.app.listen(port, () => {
      console.log(`Baileys WhatsApp Bridge listening on port ${port}`);
    });

    if (!RESTORE_ON_START) {
      console.log('RESTORE_ON_START is disabled - waiting for an explicit POST /restore-all');
      return;
    }

    if (!this.restoreScheduled) {
      this.restoreScheduled = true;
      setTimeout(() => {
        this.restoreAllClients().catch((e) => console.error('Auto-restore failed:', e));
      }, RESTORE_DELAY_MS);
    }
  }

  async stop() {
    console.log('Stopping Baileys WhatsApp Bridge…');
    await this.saveStatesToFile();

    for (const [userId, client] of this.clients) {
      try {
        client.end();
      }
      catch (error) {
        console.error(`destroy ${userId} error:`, error);
      }
    }
    this.clients.clear();

    for (const [, t] of this.reconnectTimeouts) clearTimeout(t);
    this.reconnectTimeouts.clear();

    if (this.server) this.server.close();
  }

  async cleanupClient(userId) {
    console.log(`cleanup ${userId}`);
    const client = this.clients.get(userId);
    const t = this.reconnectTimeouts.get(userId);
    if (t) clearTimeout(t);
    this.reconnectTimeouts.delete(userId);

    try {
      if (client) {
        try {
          client.end();
          console.log(`Client ${userId} destroyed successfully`);
        } catch (e) {
          console.error(`destroy fail ${userId}:`, e);
        }
      }
      this.clients.delete(userId);
      this.clientStates.delete(userId);
      this.qrCodes.delete(userId);
      this.pairingCodes.delete(userId);
      this.pairingQrSessions.delete(userId);
      this.reconnectAttempts.delete(userId);
      this.persistentChats.delete(userId); // Clear persistent chat cache
      try {
        const tStore = this.storePersistIntervals.get(userId);
        if (tStore) clearInterval(tStore);
        this.storePersistIntervals.delete(userId);
      } catch (_) {}
      this.stores.delete(userId);

      // Force delete session folder
      const sessionPath = this.sessionFolderFor(userId);
      console.log(`Attempting to delete session folder: ${sessionPath}`);
      try {
        await fs.rm(sessionPath, { recursive: true, force: true });
        console.log(`Session folder ${sessionPath} deleted successfully`);
      } catch (rmError) {
        console.error(`Failed to delete session folder ${sessionPath}:`, rmError);
        // Try alternative deletion method
        try {
          const { execSync } = require('child_process');
          execSync(`rm -rf "${sessionPath}"`, { stdio: 'ignore' });
          console.log(`Session folder ${sessionPath} deleted using alternative method`);
        } catch (execError) {
          console.error(`Alternative deletion also failed for ${sessionPath}:`, execError);
        }
      }

      return { message: 'Client cleaned up successfully', userId };
    } catch (error) {
      console.error(`cleanup error ${userId}:`, error);
      throw error;
    }
  }

  /* ---------------------------- Admin endpoints ---------------------------- */

  async disconnectUser(userId, reason = 'admin_request') {
    console.log(`Admin disconnect requested for user ${userId}, reason: ${reason}`);
    try {
      // For user suspension, completely clean up the session to avoid issues
      if (reason === 'user_suspended') {
        await this.cleanupClient(userId);
        return {
          success: true,
          message: `User ${userId} disconnected and session cleaned up for suspension`,
          reason: reason
        };
      } else {
        // For other reasons, just disconnect but keep session
        const client = this.clients.get(userId);
        const t = this.reconnectTimeouts.get(userId);
        if (t) clearTimeout(t);
        this.reconnectTimeouts.delete(userId);

        if (client) {
          try {
            client.end();
          } catch (e) {
            console.error(`destroy fail ${userId}:`, e);
          }
        }
        this.clients.delete(userId);
        this.clientStates.delete(userId);
        this.qrCodes.delete(userId);
        this.persistentChats.delete(userId); // Clear persistent chat cache

        // Don't delete session folder - keep it for reconnection
        return {
          success: true,
          message: `User ${userId} disconnected successfully (session preserved)`,
          reason: reason
        };
      }
    } catch (error) {
      console.error(`Failed to disconnect user ${userId}:`, error);
      return {
        success: false,
        message: `Failed to disconnect user ${userId}: ${error.message}`,
        error: error.message
      };
    }
  }

  async reconnectUser(userId, reason = 'admin_request') {
    console.log(`Admin reconnect requested for user ${userId}, reason: ${reason}`);
    try {
      // For user resume, we don't need to check for existing session
      // The user will need to scan QR code again
      this.updateClientState(userId, { hasSession: false });

      // Initialize client without existing session to generate QR code
      const result = await this.initializeClientWithReconnect(userId, { preferExistingSession: false });

      return {
        success: true,
        message: `User ${userId} reconnection initiated - QR code will be available`,
        reason: reason,
        result: result
      };
    } catch (error) {
      console.error(`Failed to reconnect user ${userId}:`, error);
      return {
        success: false,
        message: `Failed to reconnect user ${userId}: ${error.message}`,
        error: error.message
      };
    }
  }

  /* ---------------------------- Bulk restore ---------------------------- */

  async restoreAllClients() {
    if (this.restorePromise) {
      console.log('restore-all dedupe: already running');
      return this.restorePromise;
    }

    this.restorePromise = (async () => {
      console.log('Starting automatic client restoration...');
      const results = [];
      try {
        // Test basic connectivity first
        console.log(`Testing connectivity to backend at ${this.pythonBackendUrl}...`);
        try {
          const healthResponse = await axios.get(`${this.pythonBackendUrl}/webhook/whatsapp/health`, {
            timeout: 5000,
            headers: this.backendHeaders()
          });
          console.log(`Backend health check successful: ${healthResponse.status}`);
        } catch (healthError) {
          console.error(`Backend health check failed: ${healthError.message}`);
          console.log('Proceeding with local session restoration only');
          // Continue with local restoration even if backend is unavailable
        }

        // Get active users from backend with retry logic
        let activeUserIds = [];
        let backendAvailable = false;

        for (let attempt = 1; attempt <= 5; attempt++) {
          try {
            console.log(`Attempting to connect to backend (attempt ${attempt}/5)...`);
            const response = await axios.get(`${this.pythonBackendUrl}/webhook/whatsapp/active-users`, {
              timeout: 10000,
              headers: this.backendHeaders()
            });
            if (response.status === 200) {
              activeUserIds = response.data.active_users.map(user => user.id.toString());
              console.log(`Found ${activeUserIds.length} active users: ${activeUserIds.join(', ')}`);
              backendAvailable = true;
              break;
            }
          } catch (error) {
            console.error(`Failed to get active users from backend (attempt ${attempt}/5):`, error.message);
            if (attempt < 5) {
              const delay = attempt * 3; // Longer delays: 3s, 6s, 9s, 12s
              console.log(`Retrying in ${delay} seconds...`);
              await new Promise(resolve => setTimeout(resolve, delay * 1000));
            }
          }
        }

        if (!backendAvailable) {
          console.log('Backend unavailable after 5 attempts, proceeding with local session restoration');
          activeUserIds = null;
        }

        // An empty roster is indistinguishable from a backend that is not ready yet, so it
        // must never authorise a wipe - the sessions on disk are the only source of truth.
        const canWipe = this.hasUsableActiveUserList(activeUserIds);
        if (!canWipe) {
          console.warn(
            `Not wiping any sessions during restore-all: active user list is ${
              activeUserIds === null ? 'unavailable (backend unreachable)' : 'empty'
            }. All local sessions will be restored as-is.`
          );
        } else {
          await this.validateAndCleanupPersistedState(activeUserIds);
        }

        const diskIds = await this.listLocalSessionUserIds();
        const stateIds = Array.from(this.clientStates.keys());
        const all = Array.from(new Set([...diskIds, ...stateIds]));

        for (const userId of all) {
          const has = await this.hasRegisteredSession(userId);
          if (!has) {
            // Half-written QR attempt folders must not spawn pairing sockets on boot.
            console.log(`Skipping restore for ${userId} - no registered Baileys session`);
            continue;
          }

          // Skip users missing from the roster (only when we actually know who
          // is active). Disconnect and skip the restore, but never delete the
          // session folder: a user absent from one roster read may simply be
          // temporarily suspended, and wiping here forces a QR re-pair. Full
          // session removal stays reserved for the explicit 'user_suspended'
          // disconnect path.
          if (canWipe && !activeUserIds.includes(userId)) {
            console.log(`Skipping user ${userId} - not in active roster; disconnecting, session preserved`);
            try {
              await this.disconnectUser(userId, 'not_in_active_roster');
              results.push({ userId, status: 'skipped_suspended', message: 'User is not active - session preserved' });
            } catch (error) {
              console.error(`Failed to disconnect inactive user ${userId}:`, error);
              results.push({ userId, status: 'error', error: error.message });
            }
            continue;
          }

          console.log(`Restoring client ${userId} from disk`);
          try {
            this.updateClientState(userId, { hasSession: true }); // mark early
            const result = await this.initializeClientWithReconnect(userId, { preferExistingSession: true });
            results.push({ userId, status: 'success', result });
          } catch (error) {
            console.error(`Failed to restore client ${userId}:`, error);
            results.push({ userId, status: 'error', error: error.message });
          }
        }
      } catch (error) {
        console.error('Error during client restoration:', error);
      }
      return results;
    })();

    try { return await this.restorePromise; }
    finally { this.restorePromise = null; }
  }
}

/* ------------------------------- Boot ------------------------------- */
const bridge = new BaileysWhatsAppBridge();
bridge.start(process.env.PORT || 3000);

// graceful shutdown
if (!process.listenerCount('SIGTERM')) {
  process.on('SIGTERM', async () => {
    console.log('SIGTERM → graceful shutdown');
    await bridge.stop();
    process.exit(0);
  });
}
if (!process.listenerCount('SIGINT')) {
  process.on('SIGINT', async () => {
    console.log('SIGINT → graceful shutdown');
    await bridge.stop();
    process.exit(0);
  });
}

module.exports = BaileysWhatsAppBridge;
