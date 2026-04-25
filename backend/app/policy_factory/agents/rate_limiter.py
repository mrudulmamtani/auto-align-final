"""
Global Rate Limit Controller — centralized RPM/TPM enforcement for all agents.

Architecture:
  - RateLimiter singleton holds one _ModelBucket per model.
  - _ModelBucket uses a 60-second sliding window (deque of _WindowEntry).
  - acquire() blocks the calling thread until both RPM and TPM headroom exist,
    then registers the call before returning — prevents burst collisions from
    parallel threads.
  - A process-wide Semaphore caps total in-flight calls (_MAX_CONCURRENT).
  - record_actual() corrects the estimated token count after the response
    arrives, keeping TPM accounting tight.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ── Per-model rate limits (conservative — tune to your tier) ──────────────────
# gpt-5.4 is a high-capacity model; set RPM conservatively to avoid 429s.
_MODEL_LIMITS: dict[str, dict[str, int]] = {
    "gpt-5.4":      {"rpm": 50,  "tpm": 250_000},
    "gpt-4o":       {"rpm": 500, "tpm": 450_000},
    "gpt-4o-mini":  {"rpm": 500, "tpm": 2_000_000},
    "o3":           {"rpm": 20,  "tpm": 100_000},
    "o3-mini":      {"rpm": 20,  "tpm": 100_000},
    "default":      {"rpm": 50,  "tpm": 200_000},
}

# Max parallel calls across ALL agents (prevents simultaneous burst)
_MAX_CONCURRENT: int = 4

# Throttle when window is this fraction full (0.85 = 85%)
_THROTTLE_THRESHOLD: float = 0.85


@dataclass
class _WindowEntry:
    timestamp: float
    tokens: int


class _ModelBucket:
    """
    Thread-safe sliding-window rate limiter for one model.
    Tracks (timestamp, tokens) for every call in the last 60 s.
    """

    def __init__(self, rpm: int, tpm: int) -> None:
        self.rpm = rpm
        self.tpm = tpm
        self._lock = threading.Lock()
        self._window: deque[_WindowEntry] = deque()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _purge(self, now: float) -> None:
        cutoff = now - 60.0
        while self._window and self._window[0].timestamp < cutoff:
            self._window.popleft()

    def _current(self) -> tuple[int, int]:
        """Return (req_count, token_sum) for the live window. Caller holds lock."""
        reqs = len(self._window)
        toks = sum(e.tokens for e in self._window)
        return reqs, toks

    # ── Public interface ──────────────────────────────────────────────────────

    def current_load(self) -> tuple[int, int]:
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            return self._current()

    def acquire(self, estimated_tokens: int) -> float:
        """
        Block until RPM + TPM capacity exists for this call.
        Registers the call atomically to prevent races between threads.
        Returns total seconds slept (0 if no throttling was needed).
        """
        total_slept = 0.0

        while True:
            now = time.monotonic()
            with self._lock:
                self._purge(now)
                reqs, toks = self._current()

                rpm_ok = reqs < self.rpm
                tpm_ok = (toks + estimated_tokens) <= self.tpm

                if rpm_ok and tpm_ok:
                    self._window.append(_WindowEntry(now, estimated_tokens))
                    return total_slept

                # ── Compute adaptive sleep ────────────────────────────────
                # Base: time until oldest entry rolls out of the 60-s window
                oldest_ts = self._window[0].timestamp if self._window else now
                base_wait = max(0.1, (oldest_ts + 60.0) - now)

                # Backpressure: proportional to how far over threshold we are
                rpm_load = reqs / self.rpm
                tpm_load = (toks + estimated_tokens) / self.tpm
                pressure = max(0.0, max(rpm_load, tpm_load) - _THROTTLE_THRESHOLD)
                backpressure = pressure * 15.0          # up to +15 s extra at 100% load

                wait = min(base_wait + backpressure, 30.0)   # cap single sleep at 30 s

            logger.info(
                "[RateLimiter] throttling model=%s rpm=%d/%d tpm=%d/%d "
                "est_tokens=%d sleep=%.1fs",
                "?", reqs, self.rpm, toks, self.tpm, estimated_tokens, wait,
            )
            time.sleep(wait)
            total_slept += wait

    def record_actual(self, entry_timestamp: float, actual_tokens: int) -> None:
        """Replace estimated token count with actual from API response."""
        with self._lock:
            for entry in self._window:
                if abs(entry.timestamp - entry_timestamp) < 0.05:
                    entry.tokens = actual_tokens
                    return


class RateLimiter:
    """
    Process-wide singleton.  All agents share one instance so their windows
    are co-ordinated and burst collisions are impossible.

    Typical usage (inside wrapped client, not in agents directly):
        rl = RateLimiter.get()
        ts, slept = rl.acquire("gpt-5.4", estimated_tokens=3500)
        try:
            resp = raw_openai_call(...)
            rl.release("gpt-5.4", ts, resp.usage.total_tokens)
        except:
            rl.release("gpt-5.4", ts, estimated_tokens)
            raise
    """

    _instance: Optional["RateLimiter"] = None
    _init_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._buckets: dict[str, _ModelBucket] = {}
        self._bucket_lock = threading.Lock()
        # Process-wide concurrency cap — prevents N threads all entering
        # the API simultaneously even if each bucket has capacity.
        self._semaphore = threading.Semaphore(_MAX_CONCURRENT)

    @classmethod
    def get(cls) -> "RateLimiter":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
                    logger.info(
                        "[RateLimiter] initialised (max_concurrent=%d)", _MAX_CONCURRENT
                    )
        return cls._instance

    # ── Bucket management ─────────────────────────────────────────────────────

    def _bucket(self, model: str) -> _ModelBucket:
        with self._bucket_lock:
            if model not in self._buckets:
                lim = _MODEL_LIMITS.get(model, _MODEL_LIMITS["default"])
                self._buckets[model] = _ModelBucket(lim["rpm"], lim["tpm"])
                logger.info(
                    "[RateLimiter] new bucket model=%s rpm=%d tpm=%d",
                    model, lim["rpm"], lim["tpm"],
                )
        return self._buckets[model]

    # ── Acquire / Release ─────────────────────────────────────────────────────

    def acquire(self, model: str, estimated_tokens: int) -> tuple[float, float]:
        """
        Acquire capacity for one API call.
        Blocks on token/rpm budget, then blocks on concurrency semaphore.
        Returns (call_timestamp, total_seconds_slept).
        """
        bucket = self._bucket(model)
        slept = bucket.acquire(estimated_tokens)
        # Acquire semaphore AFTER bucket to avoid holding the slot during sleep
        self._semaphore.acquire()
        return time.monotonic(), slept

    def release(self, model: str, call_timestamp: float, actual_tokens: int) -> None:
        """
        Release concurrency slot and correct token accounting.
        Must be called in both success and exception paths.
        """
        self._semaphore.release()
        self._bucket(model).record_actual(call_timestamp, actual_tokens)

    # ── Observability ─────────────────────────────────────────────────────────

    def stats(self, model: str) -> dict:
        reqs, toks = self._bucket(model).current_load()
        lim = _MODEL_LIMITS.get(model, _MODEL_LIMITS["default"])
        return {
            "model":               model,
            "rpm_used":            reqs,
            "rpm_limit":           lim["rpm"],
            "rpm_pct":             round(reqs / lim["rpm"] * 100, 1),
            "tpm_used":            toks,
            "tpm_limit":           lim["tpm"],
            "tpm_pct":             round(toks / lim["tpm"] * 100, 1),
            "concurrent_slots_free": self._semaphore._value,
        }
