# """LiteLLM wrapper: key pool, failover and response caching."""
# import logging
# from dataclasses import dataclass

# import litellm
# from litellm import Cache

# log = logging.getLogger("llm")


# class AllProvidersUnavailable(Exception):
#     pass


# @dataclass
# class LLMResult:
#     reply: str
#     resolution_source: str
#     model: str
#     input_tokens: int
#     output_tokens: int
#     key_id: str | None
#     fallback_attempts: int


# def init_cache() -> None:
#     # In-memory LiteLLM cache. Key = model + full message list (+ params).
#     litellm.cache = Cache(type="local")


# def cache_enabled() -> bool:
#     return litellm.cache is not None


# def complete(
#     messages: list[dict],
#     keys: list[str],
#     model: str,
#     simulate: dict[str, int],
#     timeout: int = 30,
# ) -> LLMResult:
#     attempts = 0
#     for idx, key in enumerate(keys, start=1):
#         key_id = f"key_{idx}"

#         # Failover test hook: pretend this key's provider returned an error.
#         if simulate.get(key_id) or simulate.get("*"):
#             attempts += 1
#             continue

#         kwargs = dict(
#             model=model,
#             messages=messages,
#             api_key=key,
#             caching=True,
#             num_retries=0,   # we do our own failover across keys
#             timeout=timeout,
#         )
#         if simulate:
#             # Make simulated requests exercise a real call, not a cache hit.
#             kwargs["cache"] = {"no-cache": True}

#         try:
#             resp = litellm.completion(**kwargs)
#             text = resp.choices[0].message.content
#             if not text:
#                 raise ValueError("empty completion")
#         except Exception as exc:  # 429, quota, 5xx, timeouts, bad key...
#             # Log the exception type only - never the key.
#             log.warning("%s failed: %s", key_id, type(exc).__name__)
#             attempts += 1
#             continue

#         hit = bool((getattr(resp, "_hidden_params", None) or {}).get("cache_hit"))
#         usage = resp.usage
#         return LLMResult(
#             reply=text,
#             resolution_source="LLM_CACHE" if hit else "LIVE_INFERENCE",
#             model=model,
#             input_tokens=int(usage.prompt_tokens or 0),
#             output_tokens=int(usage.completion_tokens or 0),
#             key_id=None if hit else key_id,
#             fallback_attempts=0 if hit else attempts,
#         )

#     raise AllProvidersUnavailable()




"""LiteLLM wrapper: key pool, failover and response caching."""
import logging
from dataclasses import dataclass

import litellm
from litellm import Cache

log = logging.getLogger("llm")


class AllProvidersUnavailable(Exception):
    pass


@dataclass
class LLMResult:
    reply: str
    resolution_source: str
    model: str
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


def init_cache() -> None:
    # In-memory LiteLLM cache. Key = model + full message list (+ params).
    litellm.cache = Cache(type="local")
    _warm_up()


def _warm_up() -> None:
    """LiteLLM lazy-loads code the first time a cache hit is served (~1s on a small
    instance). Do one offline write + hit at startup so real requests never pay it."""
    try:
        msgs = [{"role": "user", "content": "__warmup__"}]
        for _ in range(2):  # 1st call stores, 2nd call is served from cache
            litellm.completion(
                model="gemini/warmup", messages=msgs, api_key="warmup",
                caching=True, mock_response="ok",
            )
    except Exception as exc:
        log.warning("cache warm-up skipped: %s", type(exc).__name__)


def cache_enabled() -> bool:
    return litellm.cache is not None


def complete(
    messages: list[dict],
    keys: list[str],
    model: str,
    simulate: dict[str, int],
    timeout: int = 30,
) -> LLMResult:
    attempts = 0
    for idx, key in enumerate(keys, start=1):
        key_id = f"key_{idx}"

        # Failover test hook: pretend this key's provider returned an error.
        if simulate.get(key_id) or simulate.get("*"):
            attempts += 1
            continue

        kwargs = dict(
            model=model,
            messages=messages,
            api_key=key,
            caching=True,
            num_retries=0,   # we do our own failover across keys
            timeout=timeout,
        )
        if simulate:
            # Make simulated requests exercise a real call, not a cache hit.
            kwargs["cache"] = {"no-cache": True}

        try:
            resp = litellm.completion(**kwargs)
            text = resp.choices[0].message.content
            if not text:
                raise ValueError("empty completion")
        except Exception as exc:  # 429, quota, 5xx, timeouts, bad key...
            # Log the exception type only - never the key.
            log.warning("%s failed: %s", key_id, type(exc).__name__)
            attempts += 1
            continue

        hit = bool((getattr(resp, "_hidden_params", None) or {}).get("cache_hit"))
        usage = resp.usage
        return LLMResult(
            reply=text,
            resolution_source="LLM_CACHE" if hit else "LIVE_INFERENCE",
            model=model,
            input_tokens=int(usage.prompt_tokens or 0),
            output_tokens=int(usage.completion_tokens or 0),
            key_id=None if hit else key_id,
            fallback_attempts=0 if hit else attempts,
        )

    raise AllProvidersUnavailable()