# Voice Scheduling Agent (FastAPI + OpenAI Realtime + Google OAuth)

Production-minded voice scheduling assistant with:
- OpenAI Realtime (WebRTC) voice I/O in browser
- FastAPI backend
- Google Calendar OAuth 2.0 only (no service accounts)
- Server-side tool execution (`create_calendar_event`)
- Confirmation required before event creation
- Structured logs + DB-backed audit logs + request correlation IDs

## 1) Prerequisites
- Docker + Docker Compose
- Google Cloud project with Calendar API enabled
- OpenAI API key

## 2) Google OAuth Setup (exact)
1. Create/select a Google Cloud project.
2. Enable **Google Calendar API**.
3. Configure OAuth consent screen.
4. Create OAuth Client ID (**Web application**).
5. Add redirect URIs:
   - `http://localhost:8000/api/auth/google/callback`
   - `https://<your-domain>/api/auth/google/callback` (for deployment)
6. Copy values into `.env`.

## 3) Environment Configuration
Create `.env` from `.env.example` and set required values:
- `OPENAI_API_KEY`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`

Important runtime settings:
- `SESSION_SECRET_KEY`
- `SESSION_COOKIE_SECURE` (`true` in production)
- `DATABASE_URL` (default SQLite at `/app/data/app.db` in Docker)
- `OPENAI_REALTIME_MODEL`, `OPENAI_REALTIME_VOICE`, `OPENAI_REALTIME_WEBRTC_URL`

## 4) Run (Docker-first)
```bash
docker compose up --build
```

Health check endpoint:
- `GET http://localhost:8000/api/health`

UIs:
- Main UI: `http://localhost:8000/`
- Realtime WebRTC client: `http://localhost:8000/client`
- Swagger: `http://localhost:8000/swagger`

## 5) End-to-End Test Steps
1. Open `http://localhost:8000/`.
2. Click **Connect Calendar** and finish Google OAuth consent.
3. Start voice mode or type messages.
4. Provide meeting details in order:
   - name
   - date
   - time
   - title is optional (defaults to `Meeting with {name}`)
5. Confirm final summary explicitly (`yes`, `confirm`).
6. Verify event is created and link is returned.

Behavior guarantees:
- Event is **never created** before explicit confirmation.
- Browser never receives Google OAuth tokens.
- Tool calls execute server-side only (`POST /api/tools/execute`).

## 6) API Surface (reviewers)
- `POST /api/session/start`
- `POST /api/chat`
- `POST /api/realtime/session`
- `POST /api/tools/execute`
- `GET /api/auth/google/start`
- `GET /api/auth/google/callback`
- `GET /api/auth/google/status`
- `POST /api/auth/google/disconnect`

## 7) Observability
- Structured JSON logs include `request_id`.
- API responses include `x-request-id` header.
- Audit records persisted in DB table `audit_logs` for critical actions (chat/tool/OAuth/realtime).

## 8) Troubleshooting
- **OAuth callback fails**
  - Verify `GOOGLE_REDIRECT_URI` exactly matches the URI configured in Google Cloud.
- **Calendar not connected**
  - Re-run `/api/auth/google/start`, confirm correct Google account consent.
- **No voice output / early interruption**
  - Use Chrome desktop, allow microphone permissions, hard-refresh page (`Ctrl+F5`).
- **CSRF validation failed**
  - Ensure requests send `X-CSRF-Token` matching CSRF cookie.
- **Realtime session creation fails**
  - Verify `OPENAI_API_KEY` and realtime model settings.

## 9) Local Dev (without Docker)
PowerShell:
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## 10) Tests
```bash
pytest -q
```
