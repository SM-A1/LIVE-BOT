from __future__ import annotations

import time
from dataclasses import dataclass

from aiogram import Bot

from app.security.logs import log_event


@dataclass(frozen=True)
class Identity:
    id: int
    username: str | None
    first_name: str
    display_name: str


class ManagerIdentity:
    """Detects the Manager Bot's identity via getMe and keeps it fresh. Nothing is hardcoded."""

    TTL = 600

    def __init__(self, bot: Bot):
        self._bot = bot
        self._ident: Identity | None = None
        self._at = 0.0

    async def refresh(self) -> Identity | None:
        try:
            me = await self._bot.get_me()
            self._ident = Identity(me.id, me.username, me.first_name, me.full_name)
            self._at = time.monotonic()
            log_event("identity.refresh", "ok", msg=f"manager bot detected: @{me.username}")
        except Exception as exc:
            log_event("identity.refresh", "error", error_code=type(exc).__name__)
        return self._ident

    async def get(self) -> Identity | None:
        if self._ident is None or time.monotonic() - self._at > self.TTL:
            await self.refresh()
        return self._ident

    @property
    def cached(self) -> Identity | None:
        return self._ident
