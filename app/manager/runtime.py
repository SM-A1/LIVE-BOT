from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.security.ratelimit import Pacer

ALLOWED_UPDATES = ["message", "callback_query", "my_chat_member"]


@dataclass
class Cache:
    commands: dict          # name/alias -> command row
    responses: list
    buttons: dict           # set_key -> rows
    welcome: object
    settings: object
    admins: set
    loaded: float


async def load_cache(repos, bot_id: int) -> Cache:
    cmds = [c for c in await repos.commands.list(bot_id) if c["enabled"]]
    by_name = {}
    for c in cmds:
        for n in [c["name"], *c["aliases"]]:
            by_name.setdefault(n, c)
    return Cache(
        commands=by_name,
        responses=[r for r in await repos.responses.list(bot_id) if r["enabled"]],
        buttons=await repos.buttons.all_for_bot(bot_id),
        welcome=await repos.welcome.get(bot_id),
        settings=await repos.bots.settings(bot_id),
        admins=set(await repos.bots.admins(bot_id)),
        loaded=time.monotonic())


class ChildRuntime:
    """Live state of one managed bot inside the shared manager process (no per-bot processes)."""

    def __init__(self, row, bot, token: str):
        self.row = row
        self.id: int = row["id"]
        self.owner_id: int = row["owner_id"]
        self.username: str = row["username"]
        self.name: str = row["first_name"]
        self.bot = bot
        self.token = token
        self.task: asyncio.Task | None = None
        self.cache: Cache | None = None
        self.pacer = Pacer(25)
        self.sem = asyncio.Semaphore(20)      # max concurrent updates for this bot
        self.inflight: set[asyncio.Task] = set()
        self.stopping = False
        self.status = "starting"
        self.restarts = 0

    async def get_cache(self, repos) -> Cache:
        if self.cache is None or time.monotonic() - self.cache.loaded > 120:
            self.cache = await load_cache(repos, self.id)
        return self.cache

    def invalidate(self) -> None:
        self.cache = None
