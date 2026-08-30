# AGENTS.md

Guidance for AI agents working in this repository.

## What This Is

**UnforgettableEvilBot** — WhatsApp chat monitoring with OpenAI importance scoring and scheduled digests delivered via Telegram or WhatsApp Business API.

- **Production:** https://relay.jroots.co/ (hostname configured in Coolify UI only; not referenced in-repo)
- **Infra:** Same Coolify/Hetzner host as `~/Work/jroots.co` and `~/Work/jroots-mcp-server`. Postgres and Redis are provisioned by Coolify.
- **Not** on the jroots Docker mesh: `docker-compose.coolify.yml` does **not** join the external `coolify` network. Do not assume DNS like `jroots-mcp:8100` from this container.

```
WhatsApp Web → Node Baileys bridge (:3000) → FastAPI (:9876)
                    ↓ webhooks (loopback)
              PostgreSQL + Redis + OpenAI
                    ↓ digests
              Telegram and/or WhatsApp Business API
```

## Commands

```bash
# Unit tests (fast, SQLite + mocks — default for agents)
pytest tests/unit/ -v -m "not integration"

# Integration / e2e (needs Postgres + Redis — see docker-compose.test.yml)
pytest tests/ -v -m "integration or e2e"
./scripts/run_tests.sh unit|integration|all

# Lint / format / types
ruff check .
black --check .
mypy app/ config/ --config-file=pyproject.toml
pre-commit run --all-files

# Local stack
cp .env.example .env   # set keys
docker compose up -d   # or: alembic upgrade head && uvicorn main:app --reload --port 9876
cd whatsapp_bridge && npm install && node bridge.js

# Migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
```

## Architecture

| Path | Role |
|------|------|
| `main.py` | FastAPI app + lifespan (scheduler, metrics :9090, create_all) |
| `docker/start.sh` | Prod entry: wait DB → alembic → bridge → uvicorn → restore-all |
| `config/settings.py` | All env vars |
| `app/api/` | Routes: webhooks, admin, health, monitoring, dashboard |
| `app/core/` | Repositories, cache, metrics, async processor, cleanup |
| `app/whatsapp/service.py` | Bridge HTTP client (inbound / QR / chats) |
| `app/whatsapp/official_service.py` | WhatsApp Business API (outbound digests only) |
| `app/openai_service/` | Analysis + digest generation |
| `app/telegram/` | Digest / notification delivery |
| `app/scheduler/digest_scheduler.py` | Every 5 min digests; daily cleanup 03:00 UTC |
| `whatsapp_bridge/bridge.js` | Baileys + Express on :3000 |
| `web/templates/` | Jinja2 admin UI |

**Dual-process container:** One image runs both bridge and API. Loopback only: `PYTHON_BACKEND_URL=http://127.0.0.1:9876`, `WHATSAPP_BRIDGE_URL` defaults to `http://localhost:3000`.

**Two WhatsApp stacks — do not conflate when debugging:**

1. **Baileys bridge** — inbound messages, QR pairing, chat list, session files under `whatsapp_sessions/`
2. **Official Business API** — outbound digest delivery only (`WHATSAPP_ACCESS_TOKEN`, phone number id)

**Admin:** `/admin/login` (`ADMIN_PASSWORD`, in-memory cookie sessions — lost on restart). **Health:** `/health`. **Metrics:** `GET /metrics` on :9876 is JSON; Prometheus exposition is on :9090 inside the container. **Docs:** `/docs`.

### Required env (see `.env.example`)

`DATABASE_URL`, `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `SECRET_KEY` (not the placeholder). Optional: Redis, WhatsApp Business API, `ADMIN_PASSWORD`, cleanup/pool tuning.

## Rules for agents

- Prefer **Alembic** for schema changes; do not hand-edit production DB.
- Prefer direct imports from `app.core.repositories`; do not grow `repository_factory` unless needed for legacy callers.
- Do not commit secrets, `.env`, or WhatsApp session material.
- Do not write Baileys exploits, session hijacks, or unauthorized WhatsApp access helpers.
- Default verification: unit tests. Use integration/e2e only when the change needs real DB/Redis/bridge.
- Russian UI/prompt strings are intentional (Ruff `RUF001` ignored). Digest prompts in `app/openai_service/analyzer.py` summarize Hebrew chats into Russian.

## Landmines

- **Dual schema init:** `start.sh` runs `alembic upgrade head`; `main.py` lifespan also calls `Base.metadata.create_all` — models and migrations can drift.
- **Postgres versions:** local `docker-compose.yml` uses Postgres **15**; CI/docs use **16**.
- **Coolify compose** omits `WHATSAPP_BRIDGE_URL` — default localhost works only because bridge shares the container.
- **Bridge state mismatch:** stale `client_states.json` vs DB user ids → health OK but chats timeout. There is no `fix_bridge_state.py` in-repo; use `POST http://localhost:3000/cleanup-stale-state` (or clear session dirs carefully).
- **`USE_OPTIMIZED_REPOSITORIES`:** does **not** select another repository module (file does not exist); only affects health/alert thresholds. Coolify sets `true`, `.env.example` has `false`.
- **`WHATSAPP_INTEGRATION.md`** may still mention Puppeteer — actual stack is **Baileys**, no Chrome.
- **Suspended users:** webhook returns **HTTP 200** with suspended detail so the bridge does not retry-storm.
- **`start_local.py`** looks for uvicorn on port **8000**; default API port is **9876**.
- Persist **`whatsapp_sessions/`** (and bridge state) across deploys or QR re-pairing is required.
- No Grafana dashboard for relay/whatsapp in the shared Grafana instance as of agent setup.
