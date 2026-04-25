"""Application configuration — reads from environment variables."""
from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    app_name: str = "Controls Intelligence Hub"
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"


@lru_cache
def get_settings() -> Settings:
    return Settings()
