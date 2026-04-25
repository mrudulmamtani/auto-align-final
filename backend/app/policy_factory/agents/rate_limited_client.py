"""
Rate-Limited OpenAI Client — drop-in replacement for OpenAI().

Every agent already does:
    self._client = OpenAI()
    resp = self._client.chat.completions.create(model=..., messages=..., ...)

Replace with:
    from .rate_limited_client import get_openai_client
    self._client = get_openai_client()

No other code changes needed. Full call semantics are preserved — no batching,
no merging, every call hits the API independently.

Features implemented:
  1. Token estimation before each call (input chars → tokens + output budget)
  2. Pre-call blocking via RateLimiter.acquire() — RPM + TPM + concurrency
  3. Post-call token correction via RateLimiter.release()
  4. Retry with exponential backoff + full jitter on 429 / connection / timeout
  5. Observable: all throttle events and retries logged at INFO/WARNING level
"""

from __future__ import annotations

import logging
import math
import random
import time
from typing import Any

from openai import OpenAI, RateLimitError, APIConnectionError, APITimeoutError
from openai.types.chat import ChatCompletion

from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# ── Retry configuration ───────────────────────────────────────────────────────
_MAX_RETRIES:    int   = 8
_BASE_BACKOFF:   float = 2.0     # seconds — doubles each attempt
_MAX_BACKOFF:    float = 120.0   # hard cap per sleep
_JITTER_FACTOR:  float = 0.30    # ±30% random jitter (full jitter prevents thundering herd)

# Retryable exception types
_RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError)

# ── Token estimation constants ────────────────────────────────────────────────
_CHARS_PER_TOKEN:     float = 3.5    # empirical for English + JSON
_MSG_OVERHEAD:        int   = 4      # tokens per message (role + formatting)
_DEFAULT_OUTPUT_EST:  int   = 2_500  # conservative output budget for structured calls
_SMALL_OUTPUT_EST:    int   = 500    # for non-structured calls


def _estimate_tokens(messages: list[dict], response_format: dict | None = None) -> int:
    """
    Estimate total tokens (input + output) for a chat completions call.
    Used to pre-check TPM headroom before the call is made.
    """
    input_chars = sum(
        len(str(m.get("content") or "")) + len(m.get("role", ""))
        for m in messages
    )
    input_tokens = math.ceil(input_chars / _CHARS_PER_TOKEN) + len(messages) * _MSG_OVERHEAD
    # Structured JSON outputs (response_format) tend to be larger
    output_estimate = _DEFAULT_OUTPUT_EST if response_format else _SMALL_OUTPUT_EST
    return input_tokens + output_estimate


# ── Wrapped completions endpoint ──────────────────────────────────────────────

class _CompletionsEndpoint:

    def __init__(self, raw_client: OpenAI, rl: RateLimiter) -> None:
        self._raw    = raw_client
        self._rl     = rl

    def create(
        self,
        model: str,
        messages: list[dict],
        **kwargs: Any,
    ) -> ChatCompletion:
        """
        Rate-limited, retry-backed chat.completions.create().

        Execution flow per call:
          1. Estimate tokens
          2. RateLimiter.acquire() — blocks if RPM/TPM/concurrency near limit
          3. Call raw OpenAI API
          4. On success  → RateLimiter.release() with actual token count
          5. On 429/conn → release slot, exponential backoff + jitter, retry
          6. On hard err → release slot, re-raise immediately
        """
        estimated = _estimate_tokens(messages, kwargs.get("response_format"))

        for attempt in range(_MAX_RETRIES):
            call_ts, slept = self._rl.acquire(model, estimated)

            if slept > 0.05:
                logger.info(
                    "[RLC] pre-call throttle model=%s attempt=%d sleep=%.1fs "
                    "est_tokens=%d stats=%s",
                    model, attempt + 1, slept, estimated,
                    self._rl.stats(model),
                )

            try:
                resp = self._raw.chat.completions.create(
                    model=model, messages=messages, **kwargs
                )
                actual = resp.usage.total_tokens if resp.usage else estimated
                self._rl.release(model, call_ts, actual)

                if attempt > 0:
                    logger.info(
                        "[RLC] recovered model=%s attempt=%d actual_tokens=%d",
                        model, attempt + 1, actual,
                    )
                return resp

            except _RETRYABLE as exc:
                self._rl.release(model, call_ts, estimated)

                if attempt == _MAX_RETRIES - 1:
                    logger.error(
                        "[RLC] exhausted %d retries model=%s: %s",
                        _MAX_RETRIES, model, exc,
                    )
                    raise

                # Full-jitter exponential backoff: sleep in [0, min(cap, base*2^n)]
                backoff_cap = min(_BASE_BACKOFF * (2 ** attempt), _MAX_BACKOFF)
                sleep_for   = random.uniform(1.0, backoff_cap)

                logger.warning(
                    "[RLC] %s model=%s attempt=%d/%d backoff=%.1fs",
                    type(exc).__name__, model, attempt + 1, _MAX_RETRIES, sleep_for,
                )
                time.sleep(sleep_for)

            except Exception:
                self._rl.release(model, call_ts, estimated)
                raise


class _ChatNamespace:
    def __init__(self, raw_client: OpenAI, rl: RateLimiter) -> None:
        self.completions = _CompletionsEndpoint(raw_client, rl)


class RateLimitedOpenAI:
    """
    Drop-in replacement for openai.OpenAI().

    Exposes the same interface agents already use:
        self._client.chat.completions.create(model=..., messages=..., **kwargs)

    All 132 calls execute independently — no semantic changes.
    """

    def __init__(self) -> None:
        self._raw = OpenAI()
        self._rl  = RateLimiter.get()
        self.chat = _ChatNamespace(self._raw, self._rl)


# ── Module-level factory (preferred) ─────────────────────────────────────────

_client_instance: RateLimitedOpenAI | None = None
_client_lock = __import__("threading").Lock()


def get_openai_client() -> RateLimitedOpenAI:
    """
    Return the process-wide RateLimitedOpenAI client.
    Agents should call this once in __init__ and store as self._client.
    The underlying OpenAI() connection is shared; thread-safe.
    """
    global _client_instance
    if _client_instance is None:
        with _client_lock:
            if _client_instance is None:
                _client_instance = RateLimitedOpenAI()
                logger.info("[RLC] RateLimitedOpenAI client initialised")
    return _client_instance
