# UnforgettableEvilBot

WhatsApp chat monitoring system that uses OpenAI to analyze message importance, generate intelligent digests, and deliver them via Telegram or WhatsApp. Built with FastAPI, Node.js (Baileys), and PostgreSQL.

## Architecture

```
WhatsApp ──▶ Node.js Bridge (Baileys) ──▶ FastAPI Backend ──▶ OpenAI Analysis
                                               │
                              ┌─────────────────┼─────────────────┐
                              ▼                 ▼                 ▼
                         PostgreSQL         Telegram          WhatsApp
                         + Redis            Delivery          Delivery
```

**Python backend** (FastAPI) handles API, scheduling, and business logic.
**Node.js bridge** (Express + @whiskeysockets/baileys) maintains persistent WhatsApp Web sessions and forwards messages via webhooks.

## Features

- **Multi-user WhatsApp monitoring** with per-user chat selection
- **AI-powered message analysis** -- importance scoring, categorization, and digest generation via OpenAI (GPT-4o-mini default)
- **Flexible delivery** -- Telegram channels or WhatsApp Official API, configurable per user
- **Scheduled digests** with configurable intervals (daily, custom hours)
- **Admin web panel** for user management, chat configuration, and system monitoring
- **Health monitoring** with database, cache, OpenAI, Telegram, and WhatsApp bridge checks
- **Background task processing** with async queue and priority levels
- **Rate limiting**, circuit breaker, and request tracing
- **Redis caching** with multi-layer (memory + Redis) strategy
- **Automated data cleanup** for messages, digests, and system logs

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0, Alembic |
| WhatsApp Bridge | Node.js 18+, Express, @whiskeysockets/baileys |
| Database | PostgreSQL 16, Redis 7 |
| AI | OpenAI API (GPT-4o-mini) |
| Delivery | python-telegram-bot, WhatsApp Business API |
| Infrastructure | Docker, Docker Compose, Coolify |
| CI/CD | GitHub Actions (lint, security, unit, integration, e2e) |
| Code Quality | Ruff, Black, mypy, Bandit, pip-audit, pre-commit |

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/akushsky/UnforgettableEvilBot.git
cd UnforgettableEvilBot
cp .env.example .env   # edit with your keys
docker-compose up -d
```

Access at `http://localhost:9876` -- admin panel at `/admin/login`.

### Local Development

```bash
# Python backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # configure DATABASE_URL, OPENAI_API_KEY, etc.
alembic upgrade head
uvicorn main:app --reload --port 9876

# WhatsApp bridge (separate terminal)
cd whatsapp_bridge && npm install && node bridge.js
```

## Configuration

### Required Environment Variables

```bash
DATABASE_URL=postgresql://user:pass@localhost/unforgettable_evil_bot
SECRET_KEY=your-secret-key
ADMIN_PASSWORD=your-admin-password
OPENAI_API_KEY=sk-...
TELEGRAM_BOT_TOKEN=your-bot-token
```

### Optional

```bash
OPENAI_MODEL=gpt-4o-mini          # default model
OPENAI_MAX_TOKENS=1000
OPENAI_TEMPERATURE=0.3
REDIS_URL=redis://localhost:6379/0
REDIS_ENABLED=true
DB_POOL_SIZE=20
CLEANUP_OLD_MESSAGES_DAYS=30
CLEANUP_OLD_SYSTEM_LOGS_DAYS=7
WHATSAPP_SESSION_PATH=./whatsapp_sessions
```

See [`.env.example`](.env.example) for the full list.

## Project Structure

```
app/
  api/           # Route handlers (admin, auth, health, monitoring, users, webhooks)
  auth/          # Authentication (JWT, admin sessions)
  core/          # Business logic (repositories, DI, cache, metrics, scheduling)
  database/      # SQLAlchemy connection with lazy engine init
  models/        # ORM models and Pydantic schemas
  openai_service/# OpenAI client and digest generation
  scheduler/     # Digest scheduling and background cleanup
  telegram/      # Telegram bot integration
  whatsapp/      # WhatsApp service (bridge + official API)
whatsapp_bridge/ # Node.js Express server with Baileys
tests/
  unit/          # 537 unit tests (mocked dependencies, SQLite)
  integration/   # Workflow integration tests
  e2e/           # End-to-end tests (real DB, mocked external services)
config/          # Settings and logging configuration
web/templates/   # Jinja2 HTML templates for admin panel
```

## Testing

```bash
# Unit tests (fast, no external deps)
pytest tests/unit/ -v -m "not integration"

# Integration + E2E tests (requires PostgreSQL + Redis)
pytest tests/ -v -m "integration or e2e"

# Full suite with coverage
pytest --cov=app --cov=config --cov-report=html
```

CI runs automatically on push/PR via GitHub Actions: lint (Ruff + Black + mypy), security (Bandit + pip-audit), unit tests, and integration/e2e tests with PostgreSQL 16 and Redis 7.

## Code Quality

Pre-commit hooks run automatically on commit:

```bash
pre-commit install        # one-time setup
pre-commit run --all-files  # manual run
```

Checks: **Black** (formatting), **Ruff** (linting), **mypy** (type checking), **Bandit** (security), plus trailing whitespace, AST validation, and more.

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Comprehensive health check (DB, cache, OpenAI, Telegram, WhatsApp) |
| `GET /admin/login` | Admin login page |
| `GET /admin/users` | User management panel |
| `GET /admin/dashboard` | System dashboard with metrics |
| `POST /webhook/whatsapp/message` | WhatsApp message webhook |
| `POST /webhook/whatsapp/connected` | WhatsApp connection webhook |
| `GET /docs` | OpenAPI documentation |

## Deployment

### Docker Compose

```bash
docker-compose up -d                              # production
docker-compose -f docker-compose.dev.yml up -d    # development
docker-compose -f docker-compose.coolify.yml up -d # Coolify
```

See [DEPLOYMENT.md](DEPLOYMENT.md) and [COOLIFY_DEPLOYMENT.md](COOLIFY_DEPLOYMENT.md) for detailed instructions.

## License

MIT
