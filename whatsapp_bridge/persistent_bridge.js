/* eslint-disable no-console */
const { Client, LocalAuth } = require('whatsapp-web.js');
const QRCode = require('qrcode');
const express = require('express');
const cors = require('cors');
const fs = require('fs').promises;
const fssync = require('fs');
const path = require('path');
const axios = require('axios');

const INIT_TIMEOUT_MS = parseInt(process.env.INIT_TIMEOUT_MS || '45000', 10);
const MAX_INIT_RETRIES = parseInt(process.env.MAX_INIT_RETRIES || '2', 10); // total tries incl. first
const RESTORE_DELAY_MS = parseInt(process.env.RESTORE_DELAY_MS || '3000', 10);

class PersistentWhatsAppBridge {
  constructor() {
    this.clients = new Map();           // userId -> Client
    this.clientStates = new Map();      // userId -> state info
    this.qrCodes = new Map();           // userId -> qr string
    this.reconnectTimeouts = new Map(); // userId -> timeout
    this.initializing = new Map();      // userId -> Promise
    this.restorePromise = null;         // de-dupe restore-all
    this.restoreScheduled = false;

    this.app = express();
    this.pythonBackendUrl = process.env.PYTHON_BACKEND_URL || 'http://127.0.0.1:9876';

    this.stateFile = './client_states.json';
    // Use environment variable for session path, fallback to local sessions
    this.sessionsRoot = process.env.WHATSAPP_SESSION_PATH || path.resolve('./sessions');
    console.log(`WhatsApp Bridge sessions root: ${this.sessionsRoot}`);
    if (!fssync.existsSync(this.sessionsRoot)) {
      console.log(`Creating sessions directory: ${this.sessionsRoot}`);
      fssync.mkdirSync(this.sessionsRoot, { recursive: true });
    }

    // Log environment info for debugging
    console.log('Environment info:');
    console.log('- Node.js version:', process.version);
    console.log('- Platform:', process.platform);
    console.log('- Architecture:', process.arch);
    console.log('- Puppeteer executable path:', process.env.PUPPETEER_EXECUTABLE_PATH || 'default');
    console.log('- Chrome executable path:', process.env.CHROME_EXECUTABLE_PATH || 'default');

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
        try { liveState = await client.getState(); } catch (_) {}
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
        info = client.info || null;
        try { liveState = await client.getState(); } catch (_) {}
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
  inferIsGroupFromWid(wid) { return this.inferChatKindFromWid(wid) === 'group'; }

  /* ----------------------- Lifecycle / initialization ----------------------- */

  async ensureClientStarted(userId) {
    if (this.clients.get(userId) || this.initializing.has(userId)) return;
    try { await this.initializeClientWithReconnect(userId, { preferExistingSession: true }); }
    catch (e) { console.error(`ensureClientStarted failed for ${userId}:`, e.message); }
  }

  async initializeClientWithReconnect(userId, { preferExistingSession = true } = {}) {
    if (this.initializing.has(userId)) {
      console.log(`[init] dedupe: already initializing ${userId}`);
      return this.initializing.get(userId);
    }

    const run = (async () => {
      const existing = this.clients.get(userId);
      if (existing) {
        try { if ((await existing.getState()) === 'CONNECTED') {
          return { message: 'Client already connected', userId, connected: true };
        }} catch (_) {}
      }

      const hasSession = preferExistingSession ? await this.checkSessionExists(userId) : false;
      console.log(`Initializing WA client for ${userId} (hasSession=${hasSession})`);

      let lastError = null;
      for (let attempt = 1; attempt <= Math.max(1, MAX_INIT_RETRIES); attempt++) {
        const client = new Client({
          authStrategy: new LocalAuth({
            clientId: userId,              // folder: sessions/session-<userId>
            dataPath: this.sessionsRoot,
          }),
          puppeteer: {
            headless: true,
            args: [
              '--no-sandbox',
              '--disable-setuid-sandbox',
              '--disable-dev-shm-usage',
              '--disable-gpu',
              '--disable-web-security',
              '--disable-features=VizDisplayCompositor',
              '--disable-background-timer-throttling',
              '--disable-backgrounding-occluded-windows',
              '--disable-renderer-backgrounding',
              '--disable-field-trial-config',
              '--disable-ipc-flooding-protection',
              '--enable-logging',
              '--log-level=0',
              '--v=1',
            ],
            timeout: 60000,
            protocolTimeout: 60000,
          },
          restartOnAuthFail: true,
          takeoverOnConflict: true,
          takeoverTimeoutMs: 30000,
          webVersionCache: {
            type: 'local',
            path: path.join(this.sessionsRoot, 'web-cache'),
          },
        });

        // attach handlers once per attempt
        await this.setupClientHandlers(client, userId);
        this.clients.set(userId, client);
        this.updateClientState(userId, {
          hasSession,
          lastInitialized: new Date().toISOString(),
          connected: false,
        });

        try {
          await this.withTimeout(client.initialize(), INIT_TIMEOUT_MS, `client.initialize(${userId})`);
          // if initialize resolves, we return control to events; route already returns success
          return { message: 'Client initialization started', userId, hasSession };
        } catch (err) {
          lastError = err;
          console.error(`[init] attempt ${attempt} failed for ${userId}:`, err?.message || err);
          // Hard stop this attempt's client/browser
          try { await client.destroy(); } catch (_) {}
          this.clients.delete(userId);

          // Optionally wipe bad session and retry clean
          const shouldWipe = process.env.WIPE_BAD_SESSIONS === '1' && hasSession;
          if (shouldWipe) {
            console.warn(`[init] wiping session for ${userId} and retrying…`);
            try { await fs.rm(this.sessionFolderFor(userId), { recursive: true, force: true }); }
            catch (e) { console.error(`[init] wipe failed for ${userId}:`, e?.message || e); }
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

  async setupClientHandlers(client, userId) {
    client.on('qr', (qr) => {
      console.log(`QR for ${userId}`);
      this.qrCodes.set(userId, qr);
    });

    client.on('loading_screen', (p, m) => console.log(`load ${userId}: ${p}% - ${m}`));
    client.on('change_state', (s) => console.log(`state ${userId}: ${s}`));

    // Add Puppeteer debugging
    client.on('puppeteer_page_created', (page) => {
      console.log(`Puppeteer page created for ${userId}`);
      page.on('console', (msg) => {
        if (msg.type() === 'error') {
          console.log(`Page error for ${userId}:`, msg.text());
        }
      });
      page.on('pageerror', (error) => {
        console.log(`Page error for ${userId}:`, error.message);
      });
    });

    client.on('authenticated', () => {
      console.log(`authenticated ${userId}`);
      this.updateClientState(userId, { authFailure: false, hasSession: true });

            // Set up message handling even if ready event doesn't fire
      setTimeout(async () => {
        const state = this.clientStates.get(userId) || {};
        if (!state.connected) {
          console.log(`Setting up message handling for ${userId} after authentication`);
          this.updateClientState(userId, {
            connected: true,
            lastSeen: new Date().toISOString(),
            hasSession: true,
          });

          // Force ensure web is loaded and notify backend
          try {
            const client = this.clients.get(userId);
            if (client) {
              await this.ensureWebLoaded(client);
              console.log(`Web interface loaded for ${userId}`);

              // Notify backend that client is connected
              axios.post(`${this.pythonBackendUrl}/webhook/whatsapp/connected`, {
                userId,
                timestamp: new Date().toISOString(),
                clientInfo: client.info || { connected: true },
              }).catch((err) => console.error(`notify backend failed ${userId}:`, err));
            }
          } catch (e) {
            console.log(`Force web load failed for ${userId}:`, e.message);
          }
        }
      }, 3000);

      // Additional fallback: check if client is ready after a longer delay
      setTimeout(async () => {
        const state = this.clientStates.get(userId) || {};
        const client = this.clients.get(userId);
        if (client && !state.connected) {
          try {
            const st = await client.getState();
            if (st === 'CONNECTED') {
              console.log(`Force setting client ${userId} as ready after delay`);
              this.updateClientState(userId, {
                connected: true,
                lastSeen: new Date().toISOString(),
                hasSession: true,
              });

              // Force trigger ready-like behavior
              try {
                await this.ensureWebLoaded(client);
                console.log(`Web interface loaded for ${userId} (delayed)`);

                // Notify backend
                axios.post(`${this.pythonBackendUrl}/webhook/whatsapp/connected`, {
                  userId,
                  timestamp: new Date().toISOString(),
                  clientInfo: { connected: true, forced: true },
                }).catch((err) => console.error(`notify backend failed ${userId}:`, err));
              } catch (e) {
                console.log(`Delayed web load failed for ${userId}:`, e.message);
              }
            }
          } catch (e) {
            console.log(`State check failed for ${userId}:`, e.message);
          }
        }
      }, 10000);
    });

    client.on('ready', async () => {
      console.log(`ready ${userId}`);
      this.updateClientState(userId, {
        connected: true,
        lastSeen: new Date().toISOString(),
        hasSession: true,
      });

      setTimeout(async () => {
        try {
          await this.ensureWebLoaded(client);
          await client.getChats().catch(() => {});
        } catch (e) {
          console.log(`warmup getChats failed ${userId}: ${e.message}`);
        }
      }, 400);

      axios.post(`${this.pythonBackendUrl}/webhook/whatsapp/connected`, {
        userId,
        timestamp: new Date().toISOString(),
        clientInfo: client.info,
      }).catch((err) => console.error(`notify backend failed ${userId}:`, err));

      this.qrCodes.delete(userId);
    });

    client.on('message_create', async (message) => {
      console.log(`Received message for ${userId}: ${message.body?.substring(0, 50)}...`);
      try { await this.handleIncomingMessage(userId, message); }
      catch (e) { console.error(`handle msg ${userId}:`, e); }
    });

    // Add additional message event handlers for debugging
    client.on('message', async (message) => {
      console.log(`Message event for ${userId}: ${message.body?.substring(0, 50)}...`);
    });

    client.on('message_revoke_everyone', async (message) => {
      console.log(`Message revoked for ${userId}: ${message.body?.substring(0, 50)}...`);
    });

    client.on('disconnected', (reason) => {
      console.log(`disconnected ${userId}: ${reason}`);
      this.updateClientState(userId, {
        connected: false,
        lastDisconnected: new Date().toISOString(),
        disconnectReason: reason,
      });
      const old = this.reconnectTimeouts.get(userId);
      if (old) clearTimeout(old);
      const t = setTimeout(() => this.attemptReconnect(userId), 30000);
      this.reconnectTimeouts.set(userId, t);
    });

    client.on('auth_failure', async (msg) => {
      console.error(`auth_failure ${userId}: ${msg}`);
      this.updateClientState(userId, {
        authFailure: true,
        lastAuthFailure: new Date().toISOString(),
        connected: false,
      });
      if (process.env.WIPE_BAD_SESSIONS === '1') {
        try {
          await this.cleanupClient(userId);
        } catch (e) {
          console.error(`auto-wipe failed ${userId}:`, e.message);
        }
      }
    });
  }

  async attemptReconnect(userId) {
    const client = this.clients.get(userId);
    if (!client) return;
    try {
      const st = await client.getState();
      if (st === 'CONNECTED') return;
    } catch (_) {}

    console.log(`reconnect ${userId}`);
    try {
      await this.withTimeout(client.initialize(), INIT_TIMEOUT_MS, `reconnect.initialize(${userId})`);
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
        try { live = await client.getState(); } catch (_) {}
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
    console.log(`Processing incoming message for ${userId}: ${message.body?.substring(0, 50)}...`);
    const chat = await message.getChat();
    const contact = await message.getContact();

    const importance = this.calculateMessageImportance(message);
    const messageData = {
      userId,
      messageId: message.id._serialized,
      chatId: chat.id._serialized,
      chatName: chat.name || contact.pushname || contact.number,
      chatType: chat.isGroup ? 'group' : 'private',
      sender: contact.pushname || contact.number,
      content: message.body,
      timestamp: new Date(message.timestamp * 1000).toISOString(),
      importance,
      hasMedia: message.hasMedia,
    };

    try {
      await axios.post(`${this.pythonBackendUrl}/webhook/whatsapp/message`, messageData);
      console.log(`forwarded msg ${userId}`);
    } catch (error) {
      console.error(`forward msg failed ${userId}:`, error);
    }
  }

  calculateMessageImportance(message) {
    const content = (message.body || '').toLowerCase();
    const urgent = ['срочно', 'важно', 'критично', 'помощь', 'проблема'];
    const work = ['проект', 'встреча', 'дедлайн', 'задача', 'релиз'];
    if (urgent.some((k) => content.includes(k))) return 5;
    if (work.some((k) => content.includes(k))) return 4;
    if ((message.body || '').length > 100) return 3;
    return 2;
  }

  /* -------------------- Chats / Store readiness & fetch -------------------- */

  async ensureWebLoaded(client) {
    const page = client.pupPage;
    if (!page || typeof page.waitForFunction !== 'function') {
      console.log('No Puppeteer page available for web loading check');
      return;
    }

    try {
      console.log('Waiting for WhatsApp Web interface to load...');
      await page.waitForFunction(
        () => {
          const S = window?.Store;
          const hasStore = !!(S && (S.Chat || S.Chats) && (S.Msg || S.Messages));
          console.log('WhatsApp Web Store check:', { hasStore, storeKeys: S ? Object.keys(S) : 'no store' });
          return hasStore;
        },
        { timeout: 45000 }
      );
      console.log('WhatsApp Web interface loaded successfully');
    } catch (error) {
      console.log('Failed to load WhatsApp Web interface:', error.message);

      // Try to get more debugging info
      try {
        const pageContent = await page.content();
        console.log('Page title:', await page.title());
        console.log('Page URL:', page.url());
        console.log('Page content length:', pageContent.length);
      } catch (e) {
        console.log('Could not get page debugging info:', e.message);
      }
    }
  }

  async getChatsLite(client) {
    const page = client.pupPage;
    if (!page) throw new Error('Puppeteer page not available');

    const data = await page.evaluate(() => {
      const S = window.Store;
      const src =
        (S?.Chat?.getModelsArray && S.Chat.getModelsArray()) ||
        (S?.Chat?.models) ||
        (S?.Chats?.models) ||
        [];

      const safeId = (id) => {
        if (!id) return null;
        if (id._serialized) return id._serialized;
        if (id.user && id.server) return `${id.user}@${id.server}`;
        return String(id);
      };

      return src.map((c) => {
        let lastBody = null, lastTs = null;
        try {
          const msgs = c?.msgs?.getModels ? c.msgs.getModels() : (c?.msgs?._models || []);
          const last = msgs && msgs.length ? msgs[msgs.length - 1] : null;
          if (last) {
            lastBody = last.body || null;
            lastTs = (last.t ? last.t * 1000 : last.timestamp) || null;
          }
        } catch (_) {}

        const wid = safeId(c?.id);
        return {
          _wid: wid,
          name:
            c?.formattedTitle ||
            c?.name ||
            c?.contact?.name ||
            (c?.id && (c.id.user || c.id._serialized)) ||
            'Unknown',
          isGroup: !!c?.isGroup, // placeholder; fix in Node
          participants:
            (c?.groupMetadata?.participants && c.groupMetadata.participants.length) || 0,
          lastMessage: lastBody ? { body: lastBody, timestamp: lastTs } : null,
        };
      });
    });

    return data.map((row) => ({
      id: row._wid,
      name: row.name,
      isGroup: this.inferIsGroupFromWid(row._wid) || !!row.isGroup,
      participants: row.participants,
      lastMessage: row.lastMessage,
    }));
  }

  async getChatsSafe(client, userId, { totalTimeoutMs = 45000, liteFirst = true } = {}) {
    const work = (async () => {
      await this.ensureWebLoaded(client);
      const st = await client.getState().catch(() => null);
      if (st !== 'CONNECTED') {
        throw new Error(`Client ${userId} not fully connected (state=${st})`);
      }

      if (liteFirst) {
        try {
          const lite = await this.getChatsLite(client);
          if (Array.isArray(lite)) return lite;
        } catch (e) {
          console.log(`lite chats failed ${userId}, fallback:`, e.message);
        }
      }

      // fallback: map to same shape + isGroup via wid
      for (let i = 0; i < 2; i++) {
        try {
          const chats = await client.getChats();
          if (Array.isArray(chats)) {
            return chats.map((chat) => {
              const wid =
                chat?.id?._serialized ||
                (chat?.id?.user && chat?.id?.server ? `${chat.id.user}@${chat.id.server}` : null);
              return {
                id: wid,
                name: chat.name || chat.pushname || (chat.id && chat.id.user) || 'Unknown',
                isGroup: this.inferIsGroupFromWid(wid) || !!chat.isGroup,
                participants: chat.participants ? chat.participants.length : 0,
                lastMessage: chat.lastMessage
                  ? { body: chat.lastMessage.body, timestamp: chat.lastMessage.timestamp }
                  : null,
              };
            });
          }
        } catch (e) {
          const msg = e?.message || '';
          const wait =
            msg.includes('Evaluation failed') ||
            msg.includes('Target page, context or browser has been closed')
              ? 8000
              : 3000;
          await new Promise((r) => setTimeout(r, wait));
          await this.ensureWebLoaded(client).catch(() => {});
        }
      }
      throw new Error('getChats fallback failed');
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
        if (internal.connected === true) { clearInterval(interval); return resolve(true); }
        try {
          const st = await client.getState();
          // More flexible check: if state is CONNECTED, consider it ready even without client.info
          if (st === 'CONNECTED') {
            clearInterval(interval);
            return resolve(true);
          }
        } catch (_) {}
        if (Date.now() - start > timeout) { clearInterval(interval); return resolve(false); }
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
            await client.destroy();
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
      console.log(`Persistent WhatsApp Bridge listening on port ${port}`);
    });

    if (!this.restoreScheduled) {
      this.restoreScheduled = true;
      setTimeout(() => {
        this.restoreAllClients().catch((e) => console.error('Auto-restore failed:', e));
      }, RESTORE_DELAY_MS);
    }
  }

  async stop() {
    console.log('Stopping WhatsApp Bridge…');
    await this.saveStatesToFile();

    for (const [userId, client] of this.clients) {
      try { await client.destroy(); }
      catch (error) { console.error(`destroy ${userId} error:`, error); }
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
          await client.destroy();
          console.log(`Client ${userId} destroyed successfully`);
        } catch (e) {
          console.error(`destroy fail ${userId}:`, e);
        }
      }
      this.clients.delete(userId);
      this.clientStates.delete(userId);
      this.qrCodes.delete(userId);

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
            await client.destroy();
          } catch (e) {
            console.error(`destroy fail ${userId}:`, e);
          }
        }
        this.clients.delete(userId);
        this.clientStates.delete(userId);
        this.qrCodes.delete(userId);

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

        for (let attempt = 1; attempt <= 3; attempt++) {
          try {
            console.log(`Attempting to connect to backend (attempt ${attempt}/3)...`);
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
            console.error(`Failed to get active users from backend (attempt ${attempt}/3):`, error.message);
            if (attempt < 3) {
              console.log(`Retrying in ${attempt * 2} seconds...`);
              await new Promise(resolve => setTimeout(resolve, attempt * 2000));
            }
          }
        }

        if (!backendAvailable) {
          console.log('Backend unavailable after 3 attempts, proceeding with local session restoration');
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
const bridge = new PersistentWhatsAppBridge();
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

module.exports = PersistentWhatsAppBridge;
