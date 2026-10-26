from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot import media as media_util
from app.bot.keyboards.common import b, kb
from app.bot.states.wizard import on_input
from app.bot.ui import arg, esc, own, show
from app.security.validators import clean
from app.services.variables import VARIABLES_HELP, render

router = Router(name="welcome")
FIELDS = {"enabled": "enabled", "delprev": "delete_previous", "private": "private_only", "group": "group_enabled"}


def yn(v: bool) -> str:
    return "✅ ON" if v else "❌ OFF"


async def view_welcome(ev, app, bot) -> None:
    w = await app.repos.welcome.get(bot["id"])
    media = await app.repos.media.meta(bot["id"], w["media_id"]) if w["media_id"] else None
    i = bot["id"]
    text = (f"👋 <b>Welcome Message — @{esc(bot['username'])}</b>\n\nStatus: {yn(w['enabled'])}\n"
            f"Media: {media['kind'] if media else '—'}\n\n{esc(w['text'][:400])}")
    rows = [[b(f"Enabled: {yn(w['enabled'])}", f"wel:tog:{i}:enabled")],
            [b(f"Delete previous: {yn(w['delete_previous'])}", f"wel:tog:{i}:delprev")],
            [b(f"Private only: {yn(w['private_only'])}", f"wel:tog:{i}:private"), b(f"Groups: {yn(w['group_enabled'])}", f"wel:tog:{i}:group")],
            [b("✏️ Text", f"wel:text:{i}"), b("🖼 Photo/Video", f"wel:media:{i}")],
            [b("🔘 Buttons", f"btn:open:{i}:w"), b("👁 Preview", f"wel:prev:{i}")]]
    if media:
        rows.append([b("🗑 Remove media", f"wel:rmmedia:{i}")])
    await show(ev, text, kb(rows, f"bot:open:{i}"))


@router.callback_query(F.data.startswith("wel:open:"))
async def wel_open(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    bot = await own(cb, app, arg(cb, 2))
    if bot:
        await view_welcome(cb, app, bot)


@router.callback_query(F.data.startswith("wel:tog:"))
async def wel_tog(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    f = FIELDS.get(arg(cb, 3))
    if not bot or not f:
        return
    w = await app.repos.welcome.get(bot["id"])
    await app.repos.welcome.set_field(bot["id"], f, not w[f])
    app.bots.invalidate(bot["id"])
    await view_welcome(cb, app, bot)


@router.callback_query(F.data.startswith("wel:text:"))
async def wel_text(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if bot:
        await app.wizard.set(cb.from_user.id, "wel_text", bid=bot["id"])
        await show(cb, f"✏️ Send the new welcome text.\nVariables: <code>{esc(VARIABLES_HELP)}</code>", kb([], f"wel:open:{bot['id']}"))


@router.callback_query(F.data.startswith("wel:media:"))
async def wel_media(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if bot:
        await app.wizard.set(cb.from_user.id, "wel_media", bid=bot["id"])
        await show(cb, "🖼 Send a <b>photo</b> or <b>video</b> to attach. A caption replaces the welcome text.", kb([], f"wel:open:{bot['id']}"))


@router.callback_query(F.data.startswith("wel:rmmedia:"))
async def wel_rm(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if bot:
        w = await app.repos.welcome.get(bot["id"])
        await app.repos.welcome.set_field(bot["id"], "media_id", None)
        await app.repos.media.delete(bot["id"], w["media_id"])
        app.bots.invalidate(bot["id"])
        await view_welcome(cb, app, bot)


@router.callback_query(F.data.startswith("wel:prev:"))
async def wel_prev(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    w = await app.repos.welcome.get(bot["id"])
    u = cb.from_user
    vals = {"first_name": u.first_name or "", "last_name": u.last_name or "", "username": u.username or "",
            "user_id": str(u.id), "chat_id": str(u.id), "bot_username": bot["username"], "bot_name": bot["first_name"]}
    await cb.message.answer("👁 <b>Preview</b> (text only)\n\n" + render(w["text"], vals, True))


@on_input("wel_text")
async def in_wel_text(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    text = clean(m.text, 4000)
    if not bot or not text:
        return await m.answer("Please send text.")
    await app.repos.welcome.set_field(bot["id"], "text", text)
    await app.wizard.clear(m.from_user.id)
    app.bots.invalidate(bot["id"])
    await view_welcome(m, app, bot)


@on_input("wel_media")
async def in_wel_media(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    if not bot:
        return
    mid, err = await media_util.store(app, m, bot["id"], ("photo", "video"))
    if err:
        return await m.answer(f"❌ {err}")
    w = await app.repos.welcome.get(bot["id"])
    await app.repos.media.delete(bot["id"], w["media_id"])
    await app.repos.welcome.set_field(bot["id"], "media_id", mid)
    if m.caption:
        await app.repos.welcome.set_field(bot["id"], "text", clean(m.caption, 1000))
    await app.wizard.clear(m.from_user.id)
    app.bots.invalidate(bot["id"])
    await view_welcome(m, app, bot)
