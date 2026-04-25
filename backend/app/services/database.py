"""Redis connection service."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

_redis_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """Return a shared Redis connection (lazy-initialized)."""
    global _redis_pool
    if _redis_pool is None:
        settings = get_settings()
        _redis_pool = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_pool


async def close_redis() -> None:
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None


@asynccontextmanager
async def redis_session() -> AsyncGenerator[aioredis.Redis, None]:
    """Context manager for a Redis connection."""
    r = await get_redis()
    try:
        yield r
    except Exception:
        logger.exception("Redis session error")
        raise
