# Voice Scheduling Agent (OAuth2 MVP Backend)

Production-ready FastAPI backend for a voice scheduling assistant using an LLM-driven agent and Google Calendar OAuth 2.0 (3-legged) only.

## Key Behaviors
- Confirmation-before-create is enforced in the conversation layer.
- Default timezone: `America/Montreal`.
- Default duration: `30` minutes.
- Default title fallback: `Meeting with {name}`.
- `create_calendar_event` requires authenticated user/session token context.

## OAuth 2.0 Setup (Required)
1. In Google Cloud Console, create/select a project.
2. Enable **Google Calendar API**.
3. Configure **OAuth consent screen** (External or Internal as appropriate).
4. Create **OAuth Client ID** of type **Web application**.
5. Add authorized redirect URI:
  - `http://localhost:8000/api/auth/google/callback`
  - For deployed env: `https://<your-domain>/api/auth/google/callback`
6. Copy client ID and secret into `.env`.

## Environment Variables
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `APP_BASE_URL`
- `DATABASE_URL`
- `GOOGLE_CALENDAR_ID`
- `SESSION_SECRET_KEY`
- `SESSION_COOKIE_NAME`
- `CSRF_COOKIE_NAME`
- `CSRF_HEADER_NAME`

## API Endpoints
- Swagger UI: `GET /swagger`
- OpenAPI JSON: `GET /openapi.json`
- `GET /api/health`
- `POST /api/session/start`
- `GET /api/session/me`
- `POST /api/chat`
- `GET /api/realtime/session-config`
- `POST /api/tools/execute`
- `POST /api/debug/calendar/events`
- `GET /api/auth/google/start` (browser redirect mode by default)
- `GET /api/auth/google/start?redirect=false` (returns `authorization_url` JSON)
- `GET /api/auth/google/callback`
- `GET /api/auth/google/status`
- `POST /api/auth/google/disconnect`

## Connect Calendar and Test Event Creation
1. Initialize session once: `POST /api/session/start`.
  - Server issues HTTP-only cookie (`SESSION_COOKIE_NAME`, default `vsa_session`).
  - State-changing requests require CSRF header (`X-CSRF-Token`) equal to CSRF cookie value.
2. Connect Google Calendar:
  - Open `/api/auth/google/start` directly in a browser tab.
  - For API clients, call `/api/auth/google/start?redirect=false` and open returned `authorization_url`.
3. Complete consent; callback stores refresh token for your cookie session.
4. Create events:
  - `POST /api/debug/calendar/events` (cookie session auto-resolved), or
  - `POST /api/tools/execute` with `tool_name=create_calendar_event`.

If session is not connected, calendar creation returns `401/403`.
Error responses are structured and actionable via `detail.message` and `detail.action`.

## LLM Agent Orchestration
- Chat and voice turn understanding is handled by an LLM agent service.
- Backend still enforces confirmation-before-create safety and tool execution constraints.

## Production Session Notes
- Session continuity uses encrypted+signed HTTP-only cookie.
- Set `SESSION_COOKIE_SECURE=true` in HTTPS production.
- Cookie TTL is controlled by `SESSION_COOKIE_MAX_AGE_SECONDS`.
- State-changing APIs require CSRF header (`X-CSRF-Token` by default) matching CSRF cookie.

## Run (Docker)
```bash
docker compose up --build
```
Open `http://localhost:8000`.

## Run (Local)
PowerShell (Windows):
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

bash (macOS/Linux):
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Tests
```bash
pytest -q
```
