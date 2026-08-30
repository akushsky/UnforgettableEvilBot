# Mega-style full-repo review (pre-fix baseline)

Captured from parallel review agents before / during Wave 1–3 implementation on branch `fix-p0-bugfix-waves`. Plan file was not modified (operator request). Status column reflects intended remediation in this branch.

Agents: code-reviewer, silent-failure-hunter, pr-test-analyzer, type-design-analyzer, comment-analyzer.

## Critical (addressed in Wave 1–2)

| Finding | Remediaton wave |
|---------|-----------------|
| Admin mutation APIs without auth | Wave 1.1 — router-level `get_admin_auth_dependency` |
| Unauthenticated WhatsApp webhooks | Wave 1.1 — `BRIDGE_WEBHOOK_SECRET` / `X-Bridge-Secret` |
| Persist only after AI (silent message loss) | Wave 1.2 — sync persist then analyze |
| Rate limit 60/min on loopback bridge | Wave 1.2 — secret/loopback exempt + bridge retry |
| Cleanup deletes unprocessed messages | Wave 1.3 — `is_processed` required |
| Digest short time window orphans messages | Wave 1.3 — no hours_back filter |
| restore-all wipe when `active_users: []` | Wave 1.4 — empty list never wipes |
| Unauthenticated QR / monitoring / dashboard | Wave 1.1 |
| Weak admin session IDs / no SameSite | Wave 1.1 |
| Closed DB session in `/connected` background | Wave 1.2 |
| `max_tokens=1` importance analysis | Wave 2 |
| Partial WhatsApp multi-phone marks processed | Wave 2 |
| No `/disconnected` from bridge | Wave 2 |

## Important / hygiene (Wave 2–3)

| Finding | Remediaton |
|---------|------------|
| UserSettings ignored for digest/urgent | Wave 2 |
| Cleanup success spam to all users | Wave 2 |
| Admin generate-digest Telegram-only gate | Wave 2 |
| Bridge upsert only first message; getMessage stub; chats race; preferExistingSession wipe | Wave 2 |
| `create_all` after Alembic | Wave 3 |
| Dead `USE_OPTIMIZED_REPOSITORIES` | Wave 3 |
| Puppeteer / `fix_bridge_state.py` docs | Wave 3 |
| Postgres 15 vs 16 | Wave 3 |
| Tracked `*.backup` files | Wave 3 |
| `start_local.py` port 8000 | Wave 3 |
| Misleading startup-script unit fixture | Wave 3 |

## Residual risks (not fully closed)

Agents that reported “still present” for Wave 1–3 items ran against a **pre-fix snapshot**; those Criticallines are addressed on this branch. Remaining gaps (mostly from type-design / silent-failure follow-ups):

- Admin sessions remain in-memory (lost on restart / multi-worker split); membership check only — no signed cookie / Redis.
- Bridge HTTP API on `:3000` is still unauthenticated — must stay unpublished.
- Deploy must set `BRIDGE_WEBHOOK_SECRET` in Coolify before rollout or inbound webhooks return 401.
- Model vs migration drift can still hide in tests that use `create_all` in fixtures.
- `sanitize_input` still mutates message text before storage (escape at render-time not done).
- ORM/domain invariants are comments only: no DB checks on `chat_type`, `importance_score` 1–5; no unique `(user_id, chat_id)` / `(user_id, phone_number)`.
- Repository `create`/`update` take open `dict[str, Any]`; webhook Pydantic schemas still weak (`importance` unbounded, free-form `timestamp`).
- `Settings.validate_required_settings` still deferred to lifespan — imports/scripts can see placeholder secrets.
- `start.sh` `curl .../restore-all || true` still swallows restore failure (degraded boot looks healthy).
- `get_messages_for_digest` (non-important variant) still has a time window; currently unused dead code.
- Telegram `send_notification` returning `False` is not always checked by callers.

Candidate Wave 4 (not in original plan): schema CheckConstraints + unique indexes; signed/Redis admin sessions; fail-loud restore; tighten webhook schemas; store raw content / escape at HTML render.

## Deploy checklist

1. Generate and set `BRIDGE_WEBHOOK_SECRET` (same value for API + bridge process).
2. Confirm `WHATSAPP_SESSION_PATH=/app/whatsapp_sessions` and volume persistence.
3. Confirm `RESTORE_ON_START=0` under `start.sh` supervision.
4. Smoke: `/health`, admin login, bridge `/health`, send test message end-to-end.
