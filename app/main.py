from __future__ import annotations

import asyncio
import json
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiohttp import web

from app.bot.dispatcher import build_dispatcher
from app.bot.handlers.broadcast import render_for_service
from app.bot.states.wizard import Wizard
from app.config.settings import get_settings
from app.context import App
from app.database.migrate import run_migrations
from app.database.pool import Database
from app.database.repositories import Repos
from app.manager.bot_manager import BotManager
from app.manager.identity import ManagerIdentity
from app.security.crypto import TokenVault
from app.security.logs import log_event, register_secret, setup_logging
from app.security.ratelimit import Throttle
from app.services.broadcast import BroadcastService
from app.services.scripts import ScriptSandbox

log = logging.getLogger("app")


def build_web(app: App) -> web.Application:
    async def health(_):
        t = await app.repos.bots.totals()
        return web.json_response({"ok": True, "bots": t["bots"], "online": t["online"]})

    async def hook(req: web.Request):
        try:
            bot_id = int(req.match_info["bot_id"])
            data = json.loads(await req.read())
        except (ValueError, TypeError):
            return web.Response(status=400)
        ok = await app.bots.feed_webhook(bot_id, req.headers.get("X-Telegram-Bot-Api-Secret-Token", ""), data)
        return web.Response(status=200 if ok else 403)

    w = web.Application(client_max_size=1024 * 1024)
    w.add_routes([web.get("/", health), web.get("/health", health), web.post("/wh/{bot_id}", hook)])
    return w


async def main() -> None:
    s = get_settings()
    setup_logging(s.log_level)
    for secret in (s.manager_bot_token, s.encryption_key, s.database_url):
        register_secret(secret)

    db = await Database.connect(s.database_url, s.db_pool_min, s.db_pool_max)
    await run_migrations(db)
    repos = Repos(db)
    await repos.users.upsert(type("U", (), {"id": s.owner_id, "username": None, "first_name": "Owner", "last_name": None}))

    redis = None
    if s.redis_url:
        try:
            import redis.asyncio as aioredis
            redis = aioredis.from_url(s.redis_url)
            await redis.ping()
        except Exception as exc:
            log_event("redis", "error", error_code=type(exc).__name__, msg="Redis unavailable, using in-memory throttling")
            redis = None

    session = AiohttpSession(limit=1000)
    manager_bot = Bot(s.manager_bot_token, session=session,
                      default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    identity = ManagerIdentity(manager_bot)
    if await identity.refresh() is None:
        raise SystemExit("Cannot reach Telegram or MANAGER_BOT_TOKEN is invalid (getMe failed).")

    app = App(settings=s, db=db, repos=repos, vault=TokenVault(s.encryption_key), manager_bot=manager_bot,
              session=session, identity=identity, throttle=Throttle(redis), sandbox=ScriptSandbox())
    app.wizard = Wizard(repos.platform)
    app.bots = BotManager(app)
    app.broadcasts = BroadcastService(app)

    async def _render(bc):
        return await render_for_service(app, bc)
    app.broadcasts.render = _render

    runner = web.AppRunner(build_web(app))
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", s.port).start()

    await app.bots.start_all()
    await app.broadcasts.resume_all()
    await manager_bot.set_my_commands([BotCommand(command="start", description="Open the main menu"),
                                       BotCommand(command="menu", description="Main menu"),
                                       BotCommand(command="cancel", description="Cancel current action"),
                                       BotCommand(command="help", description="Help")])
    dp = build_dispatcher(app)
    await manager_bot.delete_webhook(drop_pending_updates=False)
    ident = identity.cached
    log_event("startup", "ok", msg=f"manager @{ident.username} ready; {len(app.bots.runtimes)} bot(s) starting")
    try:
        await dp.start_polling(manager_bot, allowed_updates=["message", "callback_query"], close_bot_session=False)
    finally:
        await app.bots.shutdown()
        await runner.cleanup()
        await db.close()
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
