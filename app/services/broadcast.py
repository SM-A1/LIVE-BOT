from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace

from aiogram import Bot
from aiogram.exceptions import (TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError,
                                TelegramRetryAfter, TelegramServerError)

from app.manager.sender import send_rich
from app.security.ratelimit import Pacer
from app.services.variables import vars_for

log = logging.getLogger("app.broadcast")


class BroadcastService:
    """Paced, resumable broadcasts with Telegram flood-control handling (retry_after) and backoff."""

    RATE = 20  # msgs/sec per bot, safely under Telegram's ~30/s limit

    def __init__(self, app):
        self.app = app
        self.r = app.repos
        self.tasks: dict[int, asyncio.Task] = {}
        self.watch: dict[int, tuple[int, int]] = {}
        self.render = None  # set by UI layer: async (bot_row, broadcast_id) -> (text, markup)

    async def start(self, bot_id: int, bid: int) -> bool:
        total = await self.r.broadcasts.snapshot(bid, bot_id)
        if total < 0:
            return False
        if total == 0:
            await self.r.broadcasts.set_status(bid, "done")
            return True
        self._spawn(bid)
        return True

    def _spawn(self, bid: int) -> None:
        if bid not in self.tasks:
            self.tasks[bid] = asyncio.create_task(self._run(bid))

    async def pause(self, bid: int) -> None:
        await self.r.broadcasts.set_status(bid, "paused", ("running",))

    async def resume(self, bid: int) -> None:
        if await self.r.broadcasts.set_status(bid, "running", ("paused",)):
            self._spawn(bid)

    async def cancel(self, bid: int) -> None:
        await self.r.broadcasts.set_status(bid, "cancelled", ("running", "paused", "draft"))

    async def resume_all(self) -> None:
        for bid in await self.r.broadcasts.running_ids():
            self._spawn(bid)

    async def _run(self, bid: int) -> None:
        try:
            await self._loop(bid)
        except Exception as exc:
            await self.r.broadcasts.set_status(bid, "failed")
            await self.app.audit("broadcast.run", "error", error_code=type(exc).__name__, detail=str(exc))
        finally:
            self.tasks.pop(bid, None)
            await self._notify(bid, force=True)
            self.watch.pop(bid, None)

    async def _loop(self, bid: int) -> None:
        b = await self.r.broadcasts.get_internal(bid)
        row = await self.r.bots.get_any(b["bot_id"])
        rt = self.app.bots.runtimes.get(row["id"])
        if rt:
            ctx = rt
        else:
            token = self.app.vault.decrypt(row["token_enc"])
            ctx = SimpleNamespace(bot=Bot(token, session=self.app.session), id=row["id"], pacer=Pacer(self.RATE),
                                  username=row["username"], name=row["first_name"])
        media = await self.r.media.meta(row["id"], b["media_id"]) if b["media_id"] else None
        rows = await self.r.buttons.layout(row["id"], f"b{bid}")
        last_note = 0.0
        while await self.r.broadcasts.status(bid) == "running":
            batch = await self.r.broadcasts.next_pending(bid, 20)
            if not batch:
                await self.r.broadcasts.set_status(bid, "done", ("running",))
                break
            for rec in batch:
                u = SimpleNamespace(id=rec["user_id"], first_name=rec["first_name"] or "",
                                    last_name=rec["last_name"], username=rec["username"])
                status, err = await self._send_one(ctx, b, u, media, rows)
                await self.r.broadcasts.mark(bid, u.id, status, err)
                if status == "blocked":
                    await self.r.botusers.mark_blocked(row["id"], u.id, True)
            if time.monotonic() - last_note > 4:
                last_note = time.monotonic()
                await self._notify(bid)

    async def _send_one(self, ctx, b, u, media, rows) -> tuple[str, str | None]:
        for attempt in range(4):
            try:
                await send_rich(ctx, self.r, u.id, b["text"] or "…", vars_for(ctx, u, u.id), media, rows)
                return "sent", None
            except TelegramRetryAfter as e:
                ctx.pacer.penalize(e.retry_after + 1)
                await asyncio.sleep(e.retry_after + 1)
            except TelegramForbiddenError:
                return "blocked", "blocked or deactivated"
            except TelegramBadRequest as e:
                return "failed", str(e)[:150]
            except (TelegramNetworkError, TelegramServerError):
                await asyncio.sleep(2 ** attempt)
        return "failed", "gave up after retries"

    async def _notify(self, bid: int, force: bool = False) -> None:
        w = self.watch.get(bid)
        if not w or not self.render:
            return
        try:
            b = await self.r.broadcasts.get_internal(bid)
            text, markup = await self.render(b)
            await self.app.manager_bot.edit_message_text(text, chat_id=w[0], message_id=w[1], reply_markup=markup)
            if force and b["status"] in ("done", "cancelled", "failed"):
                await self.app.manager_bot.send_message(w[0], f"📢 Broadcast #{bid} finished: <b>{b['status']}</b>.")
        except Exception:
            pass
