import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db, llm
from .config import DEFAULT_SYSTEM_PROMPT, get_settings
from .schemas import ChatRequest, ChatResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

VALID_SIM_STATUSES = {"429", "500", "502", "503"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    llm.init_cache()
    yield


app = FastAPI(title="LLM Chatbot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],  # includes X-Simulate-Failure
)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def parse_simulation(header: str | None, enabled: bool) -> dict[str, int]:
    if not enabled or not header:
        return {}
    out: dict[str, int] = {}
    for part in header.split(","):
        key, _, status = part.strip().partition("=")
        if key and status.strip() in VALID_SIM_STATUSES:
            out[key.strip()] = int(status)
    return out


@app.get("/health")
def health():
    s = get_settings()
    try:
        db.check_db()
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")
    if not s.api_keys:
        raise HTTPException(status_code=503, detail="no api keys configured")
    return {"status": "ok", "keys_configured": len(s.api_keys), "cache_enabled": llm.cache_enabled()}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, x_simulate_failure: str | None = Header(default=None)):
    start = time.perf_counter()
    s = get_settings()

    # Effective system prompt: request > stored for session > default
    system_prompt = req.system_prompt or db.get_session_prompt(req.session_id) or DEFAULT_SYSTEM_PROMPT
    history = [{"role": m["role"], "content": m["content"]} for m in db.get_history(req.session_id)]
    messages = [{"role": "system", "content": system_prompt}, *history,
                {"role": "user", "content": req.message}]

    try:
        result = llm.complete(
            messages=messages,
            keys=s.api_keys,
            model=s.model,
            simulate=parse_simulation(x_simulate_failure, s.enable_failure_simulation),
            timeout=s.request_timeout,
        )
    except llm.AllProvidersUnavailable:
        raise HTTPException(status_code=503, detail="all providers unavailable")

    metadata = {
        "resolution_source": result.resolution_source,
        "model": result.model,
        "latency_ms": 0,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "key_id": result.key_id,
        "fallback_attempts": result.fallback_attempts,
    }
    metadata["latency_ms"] = max(1, int((time.perf_counter() - start) * 1000))

    db.save_exchange(req.session_id, req.system_prompt, req.message, result.reply, metadata)
    return {"session_id": req.session_id, "reply": result.reply, "metadata": metadata}


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str):
    if not db.session_exists(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "messages": db.get_history(session_id)}
