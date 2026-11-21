# LLM Chatbot with Key Failover and Response Caching

A full-stack chatbot: React frontend, FastAPI backend, SQLite storage, and LiteLLM
for the model calls. It keeps multi-turn conversations per session, fails over between
API keys automatically, and caches responses.

## 1. Live URLs

- Frontend: `<your-frontend-url>`
- Backend: `<your-backend-url>`
- Backend health check: `<your-backend-url>/health`
- GitHub: `<your-repo-url>`

## 2. Run locally

### With Docker (recommended)

Requirements: Docker Desktop.

```bash
cp .env.example .env      # then put your real keys in .env
make up                   # backend :8000, frontend :3000
make down                 # stop (the SQLite volume is kept)
```

Open http://localhost:3000. API docs are at http://localhost:8000/docs.

### Without Docker

Backend (Python 3.12):

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export LLM_API_KEYS="KEY1,KEY2"
export LLM_MODEL="gemini/gemini-3.5-flash-lite"
export DATABASE_URL="sqlite:///./app.db"
export ALLOWED_ORIGINS="http://localhost:3000"
export ENABLE_FAILURE_SIMULATION=true

uvicorn app.main:app --reload --port 8000
python -m pytest -q       # backend tests
```

Frontend (Node 20):

```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev    # http://localhost:3000
```

### Environment variables

| Variable | Meaning |
|---|---|
| `LLM_API_KEYS` | Comma-separated key pool, at least 2. Key ids are `key_1`, `key_2`, ... in this order |
| `LLM_MODEL` | LiteLLM model name, default `gemini/gemini-3.5-flash-lite` |
| `DATABASE_URL` | SQLite location, e.g. `sqlite:////data/app.db` |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins |
| `ENABLE_FAILURE_SIMULATION` | `true` enables the `X-Simulate-Failure` header |
| `VITE_API_URL` | Frontend build argument: the backend URL the browser calls |

Real keys live only in `.env` (git-ignored) or in the hosting provider's settings.

## 3. Design decisions

### Key fallback

`LLM_API_KEYS` is split into a pool and keys get ids `key_1`, `key_2`, ... in order.
For each request the backend calls `litellm.completion` with the first key. If that call
raises anything (HTTP 429, quota exhausted, 5xx, timeout, bad key), it moves to the next key.
`fallback_attempts` counts the keys that failed before one answered. If every key fails,
the API returns `503 {"detail": "all providers unavailable"}` and nothing is written to history.
LiteLLM's own retries are turned off (`num_retries=0`) so failover across keys is the only
retry path, which makes the behavior predictable. Only exception types are logged, never keys.

The `X-Simulate-Failure` header (for example `key_1=429` or `*=429`) makes the listed keys
fail for that one request. It only works when `ENABLE_FAILURE_SIMULATION=true`. When the header
is present, the cache read is skipped so the request always makes a real call; otherwise a
previously cached message would return `LLM_CACHE` and hide the failover.

### Caching

LiteLLM's built-in in-memory cache is enabled at startup. The cache key is derived from the
model plus the full message list (system prompt, history, and the new message), so:

- the same first message in a new session is a hit,
- any different message, or the same message after a different history, is a miss.

Each response reports `LLM_CACHE` or `LIVE_INFERENCE` (read from LiteLLM's `cache_hit` flag).
A cache hit returns the identical reply text and the token usage that was stored with it;
`key_id` is `null` and `fallback_attempts` is `0`. `latency_ms` is measured by the server per
request. The cache is in memory, so it resets when the backend restarts; chat history does not.

### SQLite session storage

- One `messages` table with the columns from the brief (`session_id`, `role`, `content`,
  `metadata` JSON, `created_at` ISO-8601 UTC), plus an index on `(session_id, id)`.
- A small `sessions` table stores each session's optional system prompt.
- The database file is set by `DATABASE_URL` and lives on the `appdata` Docker volume at
  `/data/app.db`, so history survives container restarts. The schema is created automatically
  on startup.
- A user message and its assistant reply are written in **one transaction after** the model
  answers, so a failed request (422 or 503) never leaves anything in history.
- The client sends only the new message. The backend rebuilds the prompt from SQLite
  (system prompt + history + new message).
- Token counts are per request: they come from that call's usage, never a running total.
  Input tokens grow in a long conversation only because the history is part of that prompt.

### Other choices

- The default model is `gemini/gemini-3.5-flash-lite`. `gemini-2.0-flash` was shut down by
  Google, so the model is configurable through `LLM_MODEL`.
- Errors are always JSON with a `detail` field; an unhandled exception returns a generic
  500 JSON body, never a stack trace.
- Multi-stage Dockerfiles for both services; the backend runs as a non-root user.

## 4. Verification

Start the stack with `make up`, then run these (replace the URL with the live backend URL
when testing the deployment).

```bash
# Health
curl localhost:8000/health

# Live call
curl -s -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"s1","message":"What is the capital of France?"}'

# Cache hit: same message, NEW session -> LLM_CACHE, key_id null, lower latency
curl -s -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"s2","message":"What is the capital of France?"}'

# Failover: key_1 fails, key_2 answers (key_id "key_2", fallback_attempts 1)
curl -s -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"s3","message":"hello"}'

# Every key fails -> 503 {"detail":"all providers unavailable"}, nothing stored
curl -i -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"s4","message":"hello"}'

# Stored history, 404 for an unknown session, 422 for an empty message
curl -s localhost:8000/sessions/s1/messages
curl -i localhost:8000/sessions/nope/messages
curl -i -X POST localhost:8000/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"s5","message":"   "}'
```

In the UI (http://localhost:3000), every assistant reply shows its own source, model,
latency, and input/output tokens. To see the cache: send a message, refresh the page
(new session), and send the same message again. To see history survive a restart:
chat, run `make down && make up`, then call `GET /sessions/<id>/messages`.

Backend tests: `cd backend && python -m pytest -q` (13 tests covering validation, caching,
failover including real provider errors, the simulation hook, history, and session isolation).

## 5. Setup Used

- Editor: Visual Studio Code on macOS
- AI tools: `<fill in: for example Claude for planning and generating code>`
- Docker Desktop, Python 3.12, Node 20
- Model provider: Google Gemini API (two keys from two separate projects)

## 6. Bonus features

- Optional system-prompt box in the UI; the prompt is stored per session.
- The UI also shows which key answered and how many fallbacks were needed.
- Dark and light theme that follows the system setting.
- Backend test suite that runs real LiteLLM caching with mocked responses.
- WAL mode and an index on the messages table.