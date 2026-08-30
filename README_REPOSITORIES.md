# Repository Layer

## Overview

There is **one** repository module: `app/core/repositories.py`. It exposes a
singleton instance per entity (users, monitored chats, WhatsApp messages, digest
logs, settings, metrics, …).

There is no "basic vs optimized" repository split. An earlier design sketched an
`optimized_repositories.py` selected by a `USE_OPTIMIZED_REPOSITORIES`
environment variable; neither the module nor the flag exists anymore. The
repositories are plain SQLAlchemy — no caching layer inside them.

## Usage

Import the singleton you need directly:

```python
from app.core.repositories import user_repository, whatsapp_message_repository

users = user_repository.get_all(db, skip=0, limit=100)
```

`app/core/repository_factory.py` is a thin backward-compatible wrapper that
returns those same singletons:

```python
from app.core.repository_factory import repository_factory

user_repo = repository_factory.get_user_repository()
```

Prefer direct imports in new code; do not grow the factory unless a legacy caller
requires it.

## Caching

Caching lives outside the repository layer, in `cache_manager`
(`app/core/cache.py`), and is applied by the services and API routes that need
it:

- If `REDIS_ENABLED=true` and Redis is reachable, entries are stored in Redis
  with a TTL and shared across processes.
- Otherwise an in-process memory cache is used, which is per-worker and lost on
  restart.

Cache health is reported by `/health` and `/metrics`. The low-hit-ratio warning
is only raised when Redis is actually attached, because the in-process fallback
is expected to miss.

## Notes

- Some call sites (WhatsApp webhooks, digest scheduler) still issue direct
  SQLAlchemy queries instead of going through repositories. Migrating them is
  optional cleanup, not a correctness issue.
- Schema changes go through Alembic (`alembic revision --autogenerate`), never
  through `Base.metadata.create_all` at runtime.
