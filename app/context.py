from __future__ import annotations

import time
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from app.config.settings import Settings
from app.database.pool import Database
from app.database.repositories import Repos
from app.manager.identity import ManagerIdentity
from app.security.crypto import TokenVault
from app.security.logs import log_event, redact
from app.security.ratelimit import Throttle
from app.services.scripts import ScriptSandbox

DEFAULT_FEATURES = {"scripts": False, "custom_attribution": False, "new_bots": True}


@dataclass
class App:
    settings: Settings
    db: Database
    repos: Repos
    vault: TokenVault
    manager_bot: Bot
    session: AiohttpSession
    identity: ManagerIdentity
    throttle: Throttle
    sandbox: ScriptSandbox
    bots: object = None
    broadcasts: object = None
    wizard: object = None
    _feat: dict | None = field(default=None, repr=False)
    _feat_at: float = 0.0

    def is_platform_owner(self, uid: int) -> bool:
        return uid == self.settings.owner_id

    async def features(self) -> dict:
        if self._feat is None or time.monotonic() - self._feat_at > 15:
            stored = await self.repos.platform.get("features", {})
            self._feat = {**DEFAULT_FEATURES, **stored}
            self._feat_at = time.monotonic()
        return self._feat

    async def set_feature(self, name: str, value: bool) -> None:
        cur = {**DEFAULT_FEATURES, **(await self.repos.platform.get("features", {}))}
        cur[name] = value
        await self.repos.platform.set("features", cur)
        self._feat = None

    async def audit(self, action: str, status: str = "ok", *, user_id=None, bot_id=None, error_code=None, detail=None):
        """Structured stdout log + DB log row. Never raises; details are redacted."""
        detail = redact(str(detail))[:500] if detail else None
        log_event(action, status, user_id=user_id, bot_id=bot_id, error_code=error_code,
                  level=20 if status == "ok" else 40)
        try:
            await self.repos.platform.log(action, status, user_id, bot_id, error_code, detail)
        except Exception:
            pass

    async def limit_for(self, uid: int) -> int:
        u = await self.repos.users.get(uid)
        return u["bot_limit"] if u and u["bot_limit"] is not None else self.settings.max_bots_per_user
