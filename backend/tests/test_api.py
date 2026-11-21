def chat(client, sid, msg, headers=None, **extra):
    return client.post("/chat", json={"session_id": sid, "message": msg, **extra}, headers=headers or {})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_chat_live_then_cache_in_new_session(client):
    a = chat(client, "s1", "What is the capital of France?").json()
    assert a["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert a["metadata"]["key_id"] == "key_1"
    assert a["metadata"]["fallback_attempts"] == 0

    b = chat(client, "s2", "What is the capital of France?").json()
    assert b["metadata"]["resolution_source"] == "LLM_CACHE"
    assert b["reply"] == a["reply"]
    assert b["metadata"]["key_id"] is None
    assert b["metadata"]["fallback_attempts"] == 0
    assert b["metadata"]["input_tokens"] == a["metadata"]["input_tokens"]
    assert b["metadata"]["output_tokens"] == a["metadata"]["output_tokens"]


def test_different_message_not_cached(client):
    chat(client, "s1", "hello there")
    r = chat(client, "s2", "something else").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_tokens_are_per_request_not_cumulative(client):
    a = chat(client, "sa", "same length msg").json()["metadata"]["input_tokens"]
    b = chat(client, "sb", "other length msg").json()["metadata"]["input_tokens"]
    assert abs(a - b) <= 3
    r1 = chat(client, "sc", "hello").json()["metadata"]
    r2 = chat(client, "sc", "hello again").json()["metadata"]
    # each response reports only its own request's tokens (ints, not a running sum)
    assert isinstance(r2["input_tokens"], int) and isinstance(r2["output_tokens"], int)
    assert r2["output_tokens"] <= r1["output_tokens"] * 2


def test_multi_turn_history_and_isolation(client):
    chat(client, "s1", "first")
    chat(client, "s1", "second")
    chat(client, "s2", "other session")
    msgs = client.get("/sessions/s1/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"] == "first"
    assert "metadata" in msgs[1] and "metadata" not in msgs[0]
    assert all(m["role"] != "system" for m in msgs)
    assert len(client.get("/sessions/s2/messages").json()["messages"]) == 2


def test_unknown_session_404(client):
    r = client.get("/sessions/nope/messages")
    assert r.status_code == 404 and r.json() == {"detail": "session not found"}


def test_validation_422(client):
    assert client.post("/chat", json={"session_id": "s", "message": "   "}).status_code == 422
    assert client.post("/chat", json={"message": "hi"}).status_code == 422
    assert client.post("/chat", json={"session_id": "s", "message": "x" * 4001}).status_code == 422
    assert client.post("/chat", content="{bad json", headers={"content-type": "application/json"}).status_code == 422
    assert client.get("/sessions/s/messages").status_code == 404  # nothing stored


def test_simulated_failover_key1(client):
    chat(client, "s0", "warm the cache")  # even if cached, simulation must do a live call
    r = chat(client, "s1", "warm the cache", headers={"X-Simulate-Failure": "key_1=429"})
    assert r.status_code == 200
    m = r.json()["metadata"]
    assert m["key_id"] == "key_2" and m["fallback_attempts"] == 1
    assert m["resolution_source"] == "LIVE_INFERENCE"


def test_simulated_500(client):
    r = chat(client, "s1", "hi", headers={"X-Simulate-Failure": "key_1=500"})
    assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_2"


def test_all_keys_fail_503_and_not_stored(client):
    r = chat(client, "s1", "hi", headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 503 and r.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s1/messages").status_code == 404


def test_real_failover_on_provider_error(client):
    client.broken_keys.add("fake-key-1")
    r = chat(client, "s1", "hello").json()
    assert r["metadata"]["key_id"] == "key_2" and r["metadata"]["fallback_attempts"] == 1
    client.broken_keys.add("fake-key-2")
    r = chat(client, "s2", "hello again")
    assert r.status_code == 503


def test_simulation_disabled_ignores_header(client, monkeypatch):
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "false")
    r = chat(client, "s1", "hi", headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 200


def test_system_prompt_persists_for_session(client):
    chat(client, "s1", "hi", system_prompt="You are a pirate.")
    # same message in a different session without the prompt must NOT hit the pirate cache entry
    r = chat(client, "s2", "hi").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
