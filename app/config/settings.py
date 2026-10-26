from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

REQUIRED = ("DATABASE_URL", "MANAGER_BOT_TOKEN", "OWNER_ID", "ENCRYPTION_KEY")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        raise SystemExit(f"Environment variable {name} must be an integer.") from None


@dataclass(frozen=True)
class Settings:
    database_url: str
    manager_bot_token: str
    owner_id: int
    encryption_key: str
    redis_url: str | None
    log_level: str
    max_bots_per_user: int
    webhook_base_url: str | None
    port: int
    db_pool_min: int
    db_pool_max: int
    media_max_bytes: int


@lru_cache
def get_settings() -> Settings:
    missing = [k for k in REQUIRED if not os.environ.get(k, "").strip()]
    if missing:
        raise SystemExit("Missing required environment variables: " + ", ".join(missing))
    base = os.environ.get("WEBHOOK_BASE_URL", "").strip().rstrip("/") or None
    if base and not base.startswith("https://"):
        raise SystemExit("WEBHOOK_BASE_URL must start with https://")
    return Settings(
        database_url=os.environ["DATABASE_URL"].strip(),
        manager_bot_token=os.environ["MANAGER_BOT_TOKEN"].strip(),
        owner_id=_int("OWNER_ID", 0),
        encryption_key=os.environ["ENCRYPTION_KEY"].strip(),
        redis_url=os.environ.get("REDIS_URL", "").strip() or None,
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        max_bots_per_user=_int("MAX_BOTS_PER_USER", 5),
        webhook_base_url=base,
        port=_int("PORT", 8080),
        db_pool_min=_int("DB_POOL_MIN", 1),
        db_pool_max=_int("DB_POOL_MAX", 8),
        media_max_bytes=_int("MEDIA_MAX_BYTES", 8 * 1024 * 1024),
    )
