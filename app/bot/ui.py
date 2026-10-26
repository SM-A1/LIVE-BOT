from __future__ import annotations

import html

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

STATUS = {"online": "🟢 Online", "starting": "🟡 Starting", "offline": "🔴 Offline", "error": "⚠️ Error"}
DOT = {"online": "🟢", "starting": "🟡", "offline": "🔴", "error": "⚠️"}
LINE = "━━━━━━━━━━━━━━━━"


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def bar(pct: float, width: int = 10) -> str:
    n = round(width * pct / 100)
    return "▓" * n + "░" * (width - n)


def arg(cb: CallbackQuery, i: int) -> str:
    parts = (cb.data or "").split(":")
    return parts[i] if len(parts) > i else ""


def iarg(cb: CallbackQuery, i: int) -> int:
    try:
        return int(arg(cb, i))
    except ValueError:
        return -1


async def show(ev, text: str, markup=None) -> None:
    """Edit the current message in place for callbacks; send a new one for messages."""
    if isinstance(ev, CallbackQuery) and isinstance(ev.message, Message):
        try:
            await ev.message.edit_text(text, reply_markup=markup)
            return
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                return
            try:
                await ev.message.delete()
            except Exception:
                pass
        await ev.message.answer(text, reply_markup=markup)
    elif isinstance(ev, Message):
        await ev.answer(text, reply_markup=markup)


async def alert(ev, text: str) -> None:
    if isinstance(ev, CallbackQuery):
        await ev.answer(text, show_alert=True)
    else:
        await ev.answer(text)


async def own(ev, app, bot_id):
    """Ownership gate: returns the bot row only if it belongs to the acting user."""
    try:
        bid = int(bot_id)
    except (TypeError, ValueError):
        bid = -1
    row = await app.repos.bots.get_owned(bid, ev.from_user.id) if bid > 0 else None
    if not row:
        await alert(ev, "⚠️ Bot not found.")
    return row
