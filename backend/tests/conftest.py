import litellm
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("LLM_API_KEYS", "fake-key-1,fake-key-2")
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "true")

    # Use the REAL litellm.completion (so real caching + token counting run),
    # but replace the network call with mock_response. Keys listed in
    # `broken_keys` raise a 429-like error to test real (non-simulated) failover.
    real = litellm.completion
    broken_keys: set[str] = set()

    def fake_completion(**kw):
        if kw["api_key"] in broken_keys:
            raise litellm.RateLimitError("quota", llm_provider="gemini", model=kw["model"])
        last = kw["messages"][-1]["content"]
        return real(mock_response=f"Echo: {last}", **kw)

    monkeypatch.setattr(litellm, "completion", fake_completion)

    from app.main import app
    with TestClient(app) as c:
        c.broken_keys = broken_keys
        yield c
