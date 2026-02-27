# Voice Scheduling Agent (FastAPI + OpenAI Realtime + Google OAuth)

Production-minded voice scheduling assistant with:
- OpenAI Realtime WebRTC browser voice
- FastAPI backend
- Google Calendar OAuth only (no service accounts)
- Server-side tool execution only
- DB-backed audit logging + request correlation ID
- Confirm-before-create enforcement

Current runtime note:
- Sessions are currently stored in-process (`InMemorySessionStore`), so run with a single app worker (`WEB_CONCURRENCY=1`) to avoid cross-worker "Session not found" behavior.

## Runtime Modes

Use `APP_MODE` to select behavior:
- `demo`
  - Dev-friendly defaults (`LOG_LEVEL=DEBUG` unless overridden)
  - Debug endpoints and `/api/logs` enabled by default
  - Automatic DB bootstrap when schema is empty
- `prod`
  - Strict CORS and secure session settings required
  - Debug/log endpoints disabled unless valid `ADMIN_TOKEN` is provided
  - Lower verbosity (`LOG_LEVEL=INFO` unless overridden)
  - DB startup requires migration readiness

## 1) Prerequisites

- Docker + Docker Compose
- OpenAI API key
- Google Cloud project with Calendar API + OAuth consent configured

## 2) Environment Files

- Development template: `.env.example`
- Production template: `.env.prod.example`

Note: runtime mode values are `APP_MODE=demo|prod`.

Required core variables for both modes:
- `APP_MODE=demo|prod`
- `APP_BASE_URL`
- `CORS_ORIGINS`
- `DATABASE_URL`
- `OPENAI_API_KEY`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `SESSION_SECRET_KEY`

## 3) Google OAuth Redirect URI Setup

Configure your OAuth client with exact callback URIs:
- Demo local: `http://localhost:8000/api/auth/google/callback`
- Production: `https://<your-domain>/api/auth/google/callback`

`GOOGLE_REDIRECT_URI` must exactly match one configured URI.

## 4) Run in DEMO

### Option A: Docker Compose (demo)
```bash
docker compose up --build
```
App: `http://localhost:8000`

### Option B: Local Python
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 5) Run in PROD-like (Compose)

Use production compose stack (app + postgres):
```bash
docker compose -f docker-compose.prod.yml --env-file .env up --build -d
```

Optional: use a custom env file (for example tunnel/proxy URL):
```bash
docker compose -f docker-compose.prod.yml --env-file .env.tunnel up --build -d
```

Notes:
- In prod mode, startup enforces migration readiness (`DB_REQUIRE_MIGRATIONS=true`).
- `docker-compose.prod.yml` includes a `migrate` service and the app waits for migration completion before starting.
- Keep `SESSION_COOKIE_SECURE=true` and `APP_BASE_URL=https://...`.

## 6) Health and API

- Health: `GET /api/health`
- Swagger/OpenAPI are demo-only by default.

Core endpoints:
- `POST /api/session/start`
- `POST /api/chat`
- `POST /api/realtime/session`
- `POST /api/tools/execute`
- `GET /api/auth/google/start`
- `GET /api/auth/google/callback`
- `GET /api/auth/google/status`
- `POST /api/auth/google/disconnect`

Mode-gated endpoints:
- `GET /api/logs` (demo on, prod off unless admin token)
- `POST /api/debug/calendar/events` (demo on, prod off unless admin token)

In prod, pass admin token only when needed:
- Header: `X-Admin-Token: <ADMIN_TOKEN>`
- or query parameter: `?admin_token=<ADMIN_TOKEN>`

## 7) Evaluator Test Flow

1. Start app in demo mode.
2. Open `/voice`.
3. Click **Connect Calendar** and complete Google OAuth.
4. Verify callback returns to voice/chat mode and session remains active.
5. Say or type:
   - name
   - date
   - time
   - optional title
6. Verify assistant summarizes details and asks explicit confirmation.
7. Confirm with clear yes/confirm.
8. Verify event created and Google Calendar link returned.

## 8) Security and Observability

- OAuth tokens remain server-side only.
- Tool execution runs server-side only (`/api/tools/execute`).
- Structured JSON logs include `request_id`.
- API responses include `x-request-id`.
- Audit logs persist critical actions in DB (`audit_logs`).
- Logging sanitizes sensitive keys (`token`, `secret`, `authorization`, etc.).

## 9) Troubleshooting

- **OAuth callback fails**
  - Verify `GOOGLE_REDIRECT_URI` exactly matches Google Console.
- **Voice page missing in Docker**
  - Ensure image includes `client/` (Dockerfile copies `client`).
- **Port 8000 already allocated**
  - Stop conflicting process/container or change compose host port.
- **CSRF validation failed**
  - Ensure `X-CSRF-Token` matches CSRF cookie.
- **Prod startup fails with migration message**
  - Run `python -m app.db` against target DB and restart.

## 10) Running Tests

Run tests locally from the repository root.

PowerShell (Windows):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
```

bash/zsh (macOS/Linux):
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

Run a single test file:
```bash
pytest -q tests/test_tool_execution.py
```

`pytest.ini` already sets `pythonpath=.` and `testpaths=tests`.

If you see missing Google/OpenAI modules, ensure `pip install -r requirements.txt` ran in the active environment.
