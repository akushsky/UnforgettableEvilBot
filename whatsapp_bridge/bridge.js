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

class BaileysWhatsAppBridge {
  constructor() {
    this.clients = new Map();           // userId -> WASocket
    this.clientStates = new Map();      // userId -> state info
    this.qrCodes = new Map();           // userId -> qr string
    this.reconnectTimeouts = new Map(); // userId -> timeout
    this.initializing = new Map();      // userId -> Promise
    this.restorePromise = null;         // de-dupe restore-all
    this.restoreScheduled = false;
    this.persistentChats = new Map();   // userId -> cached chats (survives reconnections)
    this.stores = new Map();            // userId -> in-memory store bound to events
    this.storePersistIntervals = new Map(); // userId -> interval handle

    this.app = express();
    this.pythonBackendUrl = process.env.PYTHON_BACKEND_URL || 'http://127.0.0.1:9876';

    this.stateFile = './client_states.json';
    this.sessionsRoot = process.env.WHATSAPP_SESSION_PATH || path.resolve('./sessions');
    console.log(`Baileys WhatsApp Bridge sessions root: ${this.sessionsRoot}`);
    if (!fssync.existsSync(this.sessionsRoot)) {
      console.log(`Creating sessions directory: ${this.sessionsRoot}`);
      fssync.mkdirSync(this.sessionsRoot, { recursive: true });
    }

    // Log environment info for debugging
    console.log('Environment info:');
    console.log('- Node.js version:', process.version);
    console.log('- Platform:', process.platform);
    console.log('- Architecture:', process.arch);

    this.setupExpress();
    this.loadPersistedStates().catch(() => {});
    this.startAutoReconnect();
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
      res.json({ status: 'ok', clients: this.clients.size, clientInfo, restoreRunning: !!this.restorePromise });
    });

    this.app.post('/initialize/:userId', async (req, res) => {
      try {
        const userId = req.params.userId;
        const result = await this.initializeClientWithReconnect(userId, { preferExistingSession: true });
        res.json(result);
      } catch (error) {
        console.error(`Error initializing client ${req.params.userId}:`, error);
        res.status(500).json({ error: error.message });
      }
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
            headers: { 'User-Agent': 'WhatsApp-Bridge/1.0' }
          });
          if (response.status === 200) {
            activeUserIds = response.data.active_users.map(user => user.id.toString());
            console.log(`Found ${activeUserIds.length} active users: ${activeUserIds.join(', ')}`);
          }
        } catch (error) {
          console.error('Failed to get active users for manual cleanup:', error.message);
          return res.status(500).json({ error: 'Failed to get active users from backend' });
        }

        await this.validateAndCleanupPersistedState(activeUserIds);
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
      const hasSession = await this.checkSessionExists(userId);
      let client = this.clients.get(userId);

      if (!client && hasSession && !this.initializing.has(userId)) {
        // lazy-kick start (non-blocking)
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
    if (this.clients.get(userId) || this.initializing.has(userId)) return;
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
          if (existing.user) {
            return { message: 'Client already connected', userId, connected: true };
          }
        } catch (_) {}
      }

      const hasSession = preferExistingSession ? await this.checkSessionExists(userId) : false;
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
            browser: ['WhatsApp Bridge', 'Chrome', '1.0.0'],
            connectTimeoutMs: INIT_TIMEOUT_MS,
            defaultQueryTimeoutMs: 60000,
            emitOwnEvents: false,
            generateHighQualityLinkPreview: true,
            getMessage: async () => {
              return {
                conversation: 'hello'
              }
            }
          });

          // attach handlers once per attempt
          await this.setupClientHandlers(client, userId, saveCreds, sessionPath);
          this.clients.set(userId, client);
          this.updateClientState(userId, {
            hasSession,
            lastInitialized: new Date().toISOString(),
            connected: false,
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
        this.updateClientState(userId, {
          connected: true,
          lastSeen: new Date().toISOString(),
          hasSession: true,
        });

        // Notify backend
        axios.post(`${this.pythonBackendUrl}/webhook/whatsapp/connected`, {
          userId,
          timestamp: new Date().toISOString(),
          clientInfo: client.user || { connected: true },
        }).catch((err) => console.error(`notify backend failed ${userId}:`, err));

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
        const shouldReconnect = (lastDisconnect?.error instanceof Boom ? lastDisconnect.error.output?.statusCode : null) !== B.DisconnectReason.loggedOut;
        console.log(`connection closed for ${userId} due to ${lastDisconnect?.error}, reconnecting: ${shouldReconnect}`);

        this.updateClientState(userId, {
          connected: false,
          lastDisconnected: new Date().toISOString(),
          disconnectReason: lastDisconnect?.error?.message || 'unknown',
        });

        if (shouldReconnect) {
          const old = this.reconnectTimeouts.get(userId);
          if (old) clearTimeout(old);
          const t = setTimeout(() => this.attemptReconnect(userId), 30000);
          this.reconnectTimeouts.set(userId, t);
        }
      }
    });

    client.ev.on('creds.update', saveCreds);

    client.ev.on('messages.upsert', async (m) => {
      const msg = m.messages[0];
      if (!msg.key.fromMe && msg.message) {
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
    const client = this.clients.get(userId);
    if (!client) return;

    try {
      if (client.user) return; // Already connected
    } catch (_) {}

    console.log(`reconnect ${userId}`);
    try {
      await this.initializeClientWithReconnect(userId, { preferExistingSession: true });
    } catch (error) {
      console.error(`reconnect failed ${userId}:`, error?.message || error);
      const old = this.reconnectTimeouts.get(userId);
      if (old) clearTimeout(old);
      const t = setTimeout(() => this.attemptReconnect(userId), 120000);
      this.reconnectTimeouts.set(userId, t);
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
        if ((state.hasSession || (await this.checkSessionExists(userId))) && !ok) {
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
    const content = message.message?.conversation || message.message?.extendedTextMessage?.text || '';
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

    try {
      await axios.post(`${this.pythonBackendUrl}/webhook/whatsapp/message`, messageData);
      console.log(`forwarded msg ${userId}`);
    } catch (error) {
      console.error(`forward msg failed ${userId}:`, error);
    }

    // Ensure chat exists in cache
    try {
      const entry = this.normalizeChat(chatId, { subject: chatName, name: chatName });
      const merged = this.mergeChats(this.persistentChats.get(userId) || [], [entry]);
      this.persistentChats.set(userId, merged);
      await this.savePersistentChats(userId).catch(() => {});
    } catch (_) {}
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

  async validateAndCleanupPersistedState(activeUserIds) {
    console.log('Validating persisted state against active users...');

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
            headers: { 'User-Agent': 'WhatsApp-Bridge/1.0' }
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
              headers: { 'User-Agent': 'WhatsApp-Bridge/1.0' }
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

        // Validate and clean up stale persisted state
        if (backendAvailable && activeUserIds.length > 0) {
          await this.validateAndCleanupPersistedState(activeUserIds);
        }

        const diskIds = await this.listLocalSessionUserIds();
        const stateIds = Array.from(this.clientStates.keys());
        const all = Array.from(new Set([...diskIds, ...stateIds]));

        for (const userId of all) {
          const has = await this.checkSessionExists(userId);
          if (!has) continue;

          // Skip suspended users
          if (activeUserIds !== null && !activeUserIds.includes(userId)) {
            console.log(`Skipping suspended user ${userId} - disconnecting if connected`);
            try {
              await this.cleanupClient(userId);
              results.push({ userId, status: 'skipped_suspended', message: 'User is suspended' });
            } catch (error) {
              console.error(`Failed to cleanup suspended user ${userId}:`, error);
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
