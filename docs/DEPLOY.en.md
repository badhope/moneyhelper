# Deployment Guide

> Applies to the 2026-10 final release (empty-first onboarding · conversation hub · local encrypted backups). Read the [Quick start](quickstart.md) first.

## 1. Run locally (default)

Requirements: Python 3.10+, Node.js 20.19+ / 22.12+.

```bash
# Backend (must start inside backend/)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # optional: model/token; runs without any config too
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8787

# Frontend — pick one
cd frontend && npm install && npm run dev     # dev mode http://127.0.0.1:5198 (proxy to 8788)
cd frontend && npm run build                  # prod: built once, served by backend http://127.0.0.1:8787
```

One-click: `scripts/dev.sh` at the repo root (backend 8788 + frontend dev 5198, Ctrl-C stops both).

## 2. Docker (single container)

```bash
docker compose up -d --build     # http://<server-ip>:8787
```

- Service name `moneyhelper`, port 8787; volume `moneyhelper-data` mounts `/app/backend/data` (SQLite + backups persist across restarts).
- Env passthrough via `docker-compose.yml`: `API_TOKEN` / `ALLOWED_HOSTS` / `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`. All optional — you can also configure AI inside the app after startup.
- Health check: `/api/health` every 30s; auto-restart on failure (`restart: unless-stopped`).

## 3. LAN / public access (security first)

The app **only allows localhost by default**. Configure access before exposing it:

| Scenario | Configuration |
|---|---|
| LAN (NAS / internal hostnames) | Set `ALLOWED_HOSTS=nas.local,10.0.0.5` (comma-separated), no token |
| Public / reverse proxy / multi-user | **`API_TOKEN` is mandatory**: every `/api/*` needs `Authorization: Bearer <token>` or `?token=<token>`; the frontend shows a passcode dialog on first access |

```bash
# nginx reverse proxy example (port 8787, same-origin paths)
location / { proxy_pass http://127.0.0.1:8787; }
```

## 4. Data & backups

- All personal data lives in `backend/data/wealth.db` (SQLite, WAL). Backup packages are written to `backend/data/backups/` (inside the Docker volume — they survive container recreation).
- **Backup**: Settings → Data & Status → Export. **We recommend setting a backup passphrase** — exports then become encrypted packages (PBKDF2-derived key + Fernet); the passphrase is shown once, never stored, unrecoverable if lost. Without a passphrase, exports are plaintext with a strong warning first.
- **Restore**: Settings → Data & Status → Restore backup; pick the encrypted package and enter the same passphrase. A wrong passphrase rejects the whole import and rolls back.
- **Migration**: a backup package is a single JSON file. Copy it to a new machine and use "Restore backup" (AI keys are excluded; re-enter them after restore).

## 5. Upgrades

- Backend schema changes are applied automatically by incremental migrations in `db.py`; historical data is preserved. Backup packages carry a version field that is validated on restore.
- After a frontend upgrade, run `npm run build` (it bumps the Service Worker cache version so the old SW never serves stale assets).

## 6. Scheduled tasks

The daily morning report is driven by APScheduler (default 08:00; change the time or trigger one immediately in Settings → Daily Report). Scheduler status: `GET /api/scheduler`. Reports work with AI or the deterministic template — the service never breaks.
