from __future__ import annotations

import logging

from aiogram import Dispatcher
from aiogram.types import ErrorEvent

from app.bot.handlers import (bots, broadcast, buttons, commands, inputs, owner, responses, scripts,
                              settings, start, users, welcome)
from app.bot.middleware.guards import Guard

log = logging.getLogger("app.bot")


def build_dispatcher(app) -> Dispatcher:
    dp = Dispatcher(app=app)
    dp.message.outer_middleware(Guard())
    dp.callback_query.outer_middleware(Guard())
    dp.include_routers(start.router, owner.router, bots.router, commands.router, responses.router, welcome.router,
                       buttons.router, broadcast.router, users.router, settings.router, scripts.router, inputs.router)

    @dp.error()
    async def on_error(event: ErrorEvent, app) -> bool:
        exc = event.exception
        upd = event.update
        uid = None
        target = None
        if upd.callback_query:
            uid, target = upd.callback_query.from_user.id, upd.callback_query
        elif upd.message:
            uid, target = upd.message.from_user.id, upd.message
        log.error("handler error", exc_info=exc)  # stack trace goes to internal (redacted) logs only
        await app.audit("handler", "error", user_id=uid, error_code=type(exc).__name__, detail=str(exc))
        try:
            if upd.callback_query:
                await target.answer("⚠️ Something went wrong. Please try again.", show_alert=True)
            elif target:
                await target.answer("⚠️ Something went wrong. Please try again.")
        except Exception:
            pass
        return True

    return dp
