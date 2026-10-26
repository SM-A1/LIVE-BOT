from __future__ import annotations

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from app.security.validators import CALLBACK_RE


class Guard(BaseMiddleware):
    """Private chats only, throttling, user registry + ban check, callback validation."""

    async def __call__(self, handler, event, data):
        app = data["app"]
        is_cb = isinstance(event, CallbackQuery)
        user = event.from_user
        chat = event.message.chat if is_cb and event.message else getattr(event, "chat", None)
        if user is None or user.is_bot or chat is None or chat.type != "private":
            return None
        if not await app.throttle.hit(f"mu:{user.id}", 25, 10):
            if is_cb:
                await event.answer("⏳ Slow down a little.")
            return None
        row = await app.repos.users.upsert(user)
        if row["is_banned"] and not app.is_platform_owner(user.id):
            if is_cb:
                await event.answer("🚫 You are banned from using this service.", show_alert=True)
            return None
        if is_cb and not CALLBACK_RE.match(event.data or ""):
            await event.answer("⚠️ Invalid action.")
            return None
        try:
            return await handler(event, data)
        finally:
            if is_cb:
                try:
                    await event.answer()
                except Exception:
                    pass
