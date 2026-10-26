from __future__ import annotations

import asyncio
import hmac
import logging

from aiogram import Bot
from aiogram.exceptions import (TelegramConflictError, TelegramNetworkError, TelegramRetryAfter,
                                TelegramServerError, TelegramUnauthorizedError)
from aiogram.types import Update

from app.manager.child_handler import ChildHandler
from app.manager.runtime import ALLOWED_UPDATES, ChildRuntime

log = logging.getLogger("app.manager")


class BotManager:
    """Runs every managed bot as an asyncio task inside this one process, with crash recovery."""

    def __init__(self, app):
        self.app = app
        self.runtimes: dict[int, ChildRuntime] = {}
        self.handler = ChildHandler(app)
        self._supervisor: asyncio.Task | None = None

    # --- lifecycle ----------------------------------------------------------
    async def start_all(self) -> None:
        ids = [r["id"] for r in await self.app.repos.bots.list_runnable()]
        sem = asyncio.Semaphore(10)

        async def one(i: int):
            async with sem:
                await self.start_bot(i)
        await asyncio.gather(*(one(i) for i in ids), return_exceptions=True)
        self._supervisor = asyncio.create_task(self._supervise())

    async def start_bot(self, bot_id: int) -> ChildRuntime | None:
        repos = self.app.repos
        row = await repos.bots.get_any(bot_id)
        if not row or row["is_disabled"]:
            return None
        await self.stop_bot(bot_id, mark_offline=False)
        try:
            token = self.app.vault.decrypt(row["token_enc"])
        except ValueError:
            await repos.bots.set_status(bot_id, "error", "Stored token cannot be decrypted (check ENCRYPTION_KEY)")
            return None
        await repos.bots.set_status(bot_id, "starting")
        rt = ChildRuntime(row, Bot(token, session=self.app.session), token)
        self.runtimes[bot_id] = rt
        mode = (await repos.bots.settings(bot_id))["update_mode"]
        use_webhook = mode == "webhook" and self.app.settings.webhook_base_url
        rt.task = asyncio.create_task(self._webhook_start(rt) if use_webhook else self._poll(rt))
        return rt

    async def stop_bot(self, bot_id: int, mark_offline: bool = True, delete_webhook: bool = False) -> None:
        rt = self.runtimes.pop(bot_id, None)
        if not rt:
            return
        rt.stopping = True
        if rt.task:
            rt.task.cancel()
        for t in list(rt.inflight):
            t.cancel()
        await asyncio.gather(*(t for t in [rt.task, *rt.inflight] if t), return_exceptions=True)
        if delete_webhook:
            try:
                await rt.bot.delete_webhook()
            except Exception:
                pass
        if mark_offline:
            try:
                await self.app.repos.bots.set_status(bot_id, "offline")
            except Exception:
                pass

    async def restart_bot(self, bot_id: int):
        return await self.start_bot(bot_id)

    def invalidate(self, bot_id: int) -> None:
        rt = self.runtimes.get(bot_id)
        if rt:
            rt.invalidate()

    async def shutdown(self) -> None:
        if self._supervisor:
            self._supervisor.cancel()
        for bid in list(self.runtimes):
            await self.stop_bot(bid, mark_offline=False)

    # --- status helpers -------------------------------------------------------
    async def _status(self, rt: ChildRuntime, status: str, error: str | None = None) -> None:
        if rt.status != status or error:
            rt.status = status
            try:
                await self.app.repos.bots.set_status(rt.id, status, error)
            except Exception:
                pass

    def _spawn(self, rt: ChildRuntime, upd: Update) -> None:
        async def run():
            async with rt.sem:
                await self.handler.handle(rt, upd)
        t = asyncio.create_task(run())
        rt.inflight.add(t)
        t.add_done_callback(rt.inflight.discard)

    # --- polling --------------------------------------------------------------
    async def _poll(self, rt: ChildRuntime) -> None:
        offset, backoff, fails = None, 1.0, 0
        try:
            while not rt.stopping:
                try:
                    if rt.status != "online" or offset is None:
                        await rt.bot.delete_webhook(drop_pending_updates=False)
                    updates = await rt.bot.get_updates(offset=offset, timeout=25, limit=100,
                                                       allowed_updates=ALLOWED_UPDATES, request_timeout=40)
                    if rt.status != "online":
                        await self._status(rt, "online")
                        await self.app.audit("bot.online", "ok", bot_id=rt.id)
                    fails, backoff = 0, 1.0
                    for u in updates:
                        offset = u.update_id + 1
                        self._spawn(rt, u)
                except TelegramUnauthorizedError:
                    await self._status(rt, "error", "Token was revoked or is no longer valid. Update it with ➕ Add Bot.")
                    await self.app.audit("bot.error", "error", bot_id=rt.id, error_code="unauthorized")
                    return
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                except TelegramConflictError:
                    await self._status(rt, "error", "Another process is polling this bot (or a webhook is set).")
                    await asyncio.sleep(30)
                except (TelegramNetworkError, TelegramServerError, asyncio.TimeoutError) as exc:
                    fails += 1
                    if fails >= 5:
                        await self._status(rt, "error", "Cannot reach Telegram; retrying automatically.")
                    log.warning("poll error bot=%s %s", rt.id, type(exc).__name__)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
        except asyncio.CancelledError:
            raise

    # --- webhook --------------------------------------------------------------
    async def _webhook_start(self, rt: ChildRuntime) -> None:
        try:
            await rt.bot.set_webhook(url=f"{self.app.settings.webhook_base_url}/wh/{rt.id}",
                                     secret_token=self.app.vault.webhook_secret(rt.id),
                                     allowed_updates=ALLOWED_UPDATES, drop_pending_updates=False)
            await self._status(rt, "online")
        except TelegramUnauthorizedError:
            await self._status(rt, "error", "Token was revoked or is no longer valid.")
        except Exception as exc:
            await self._status(rt, "error", "Could not register webhook with Telegram.")
            await self.app.audit("bot.webhook", "error", bot_id=rt.id, error_code=type(exc).__name__, detail=str(exc))

    async def feed_webhook(self, bot_id: int, secret: str, data: dict) -> bool:
        rt = self.runtimes.get(bot_id)
        if not rt or not hmac.compare_digest(secret or "", self.app.vault.webhook_secret(bot_id)):
            return False
        self._spawn(rt, Update.model_validate(data, context={"bot": rt.bot}))
        return True

    # --- supervisor -----------------------------------------------------------
    async def _supervise(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(30)
            tick += 1
            try:
                for bid, rt in list(self.runtimes.items()):
                    if rt.task and rt.task.done() and not rt.stopping and rt.status != "error":
                        rt.restarts += 1
                        await self.app.audit("bot.recover", "ok", bot_id=bid, detail=f"restart #{rt.restarts}")
                        await self.start_bot(bid)
                if tick % 2880 == 0:  # daily
                    await self.app.repos.platform.prune_logs()
            except Exception as exc:
                log.error("supervisor error %s", type(exc).__name__)
