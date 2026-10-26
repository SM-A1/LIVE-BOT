from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot import media as media_util
from app.bot.keyboards.common import b, kb
from app.bot.states.wizard import on_input
from app.bot.ui import STATUS, alert, arg, bar, esc, iarg, own, show
from app.security.validators import clean
from app.services.variables import VARIABLES_HELP

router = Router(name="broadcast")
ST = {"draft": "📝 Draft", "running": "▶️ Running", "paused": "⏸ Paused", "cancelled": "❌ Cancelled",
      "done": "✅ Completed", "failed": "⚠️ Failed"}


async def render(app, bot, bc):
    i, bid = bot["id"], bc["id"]
    if bc["status"] == "draft":
        n = await app.repos.broadcasts.eligible(i)
        text = (f"📢 <b>Broadcast #{bid} — {ST['draft']}</b>\n\nType: {bc['content_type']}\n"
                f"👥 Recipients now: <b>{n:,}</b>\n\n{esc(bc['text'][:500]) or '<i>(no text)</i>'}")
        rows = [[b("🔘 Buttons", f"btn:open:{i}:b{bid}"), b("▶️ Start", f"bc:ask:{i}:{bid}")],
                [b("🗑 Discard", f"bc:disc:{i}:{bid}")]]
        return text, kb(rows, f"bc:home:{i}")
    p = await app.repos.broadcasts.progress(bid)
    done = p["sent"] + p["failed"] + p["blocked"]
    pct = (done / p["total"] * 100) if p["total"] else 100
    text = (f"📢 <b>Broadcast #{bid} — {ST[bc['status']]}</b>\n\n👥 Total users: <b>{p['total']:,}</b>\n"
            f"✅ Sent: {p['sent']:,}\n❌ Failed: {p['failed']:,}\n⛔ Blocked: {p['blocked']:,}\n⏳ Remaining: {p['remaining']:,}\n\n"
            f"{bar(pct)} {pct:.0f}%")
    row = [b("🔄 Refresh", f"bc:view:{i}:{bid}")]
    if bc["status"] == "running":
        row = [b("⏸ Pause", f"bc:pause:{i}:{bid}"), b("❌ Cancel", f"bc:cancel:{i}:{bid}")] + row
    elif bc["status"] == "paused":
        row = [b("▶️ Resume", f"bc:resume:{i}:{bid}"), b("❌ Cancel", f"bc:cancel:{i}:{bid}")] + row
    return text, kb([row], f"bc:home:{i}")


async def render_for_service(app, bc):
    bot = await app.repos.bots.get_any(bc["bot_id"])
    return await render(app, bot, bc)


async def _get(cb, app):
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return None, None
    bc = await app.repos.broadcasts.get(bot["id"], iarg(cb, 3))
    if not bc:
        await alert(cb, "⚠️ Broadcast not found.")
        return None, None
    return bot, bc


@router.callback_query(F.data.startswith("bc:home:"))
async def bc_home(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    items = await app.repos.broadcasts.list(bot["id"])
    rows = [[b("➕ New Broadcast", f"bc:new:{bot['id']}")]]
    rows += [[b(f"#{x['id']} · {ST[x['status']]} · {x['total']:,}", f"bc:view:{bot['id']}:{x['id']}")] for x in items]
    await show(cb, f"📢 <b>Broadcast — @{esc(bot['username'])}</b>\n\nSend a message to all users of this bot, "
                   f"paced to respect Telegram's limits.", kb(rows, f"bot:open:{bot['id']}"))


@router.callback_query(F.data.startswith("bc:new:"))
async def bc_new(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    if await app.repos.broadcasts.active_count(bot["id"]):
        return await alert(cb, "⚠️ Another broadcast is still running or paused for this bot.")
    await app.wizard.set(cb.from_user.id, "bc_content", bid=bot["id"])
    await show(cb, "📢 Send the message to broadcast: <b>text</b>, <b>photo</b>, <b>video</b>, <b>document</b> or <b>audio</b> "
                   f"(caption = text).\nVariables: <code>{esc(VARIABLES_HELP)}</code>", kb([], f"bc:home:{bot['id']}"))


@on_input("bc_content")
async def in_content(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    if not bot:
        return
    mid, ctype, text = None, "text", clean(m.text, 4000)
    if media_util.extract(m):
        mid, err = await media_util.store(app, m, bot["id"], ("photo", "video", "document", "audio"))
        if err:
            return await m.answer(f"❌ {err}")
        ctype, text = media_util.extract(m)[0], clean(m.caption, 1000)
    elif not text:
        return await m.answer("Please send text or a supported file.")
    bc = await app.repos.broadcasts.create(bot["id"], m.from_user.id, ctype, text, mid)
    await app.wizard.clear(m.from_user.id)
    t, mk = await render(app, bot, bc)
    await m.answer(t, reply_markup=mk)


@router.callback_query(F.data.startswith("bc:view:"))
async def bc_view(cb: CallbackQuery, app) -> None:
    bot, bc = await _get(cb, app)
    if bc:
        if bc["status"] in ("running", "paused") and isinstance(cb.message, Message):
            app.broadcasts.watch[bc["id"]] = (cb.message.chat.id, cb.message.message_id)
        t, mk = await render(app, bot, bc)
        await show(cb, t, mk)


@router.callback_query(F.data.startswith("bc:ask:"))
async def bc_ask(cb: CallbackQuery, app) -> None:
    bot, bc = await _get(cb, app)
    if not bc or bc["status"] != "draft":
        return
    n = await app.repos.broadcasts.eligible(bot["id"])
    if n == 0:
        return await alert(cb, "No eligible recipients yet.")
    await show(cb, f"⚠️ <b>Send to {n:,} users?</b>\n\nThis cannot be undone once started.",
               kb([[b("✅ Yes, start", f"bc:start:{bot['id']}:{bc['id']}")]], f"bc:view:{bot['id']}:{bc['id']}"))


@router.callback_query(F.data.startswith("bc:start:"))
async def bc_start(cb: CallbackQuery, app) -> None:
    bot, bc = await _get(cb, app)
    if not bc:
        return
    if bot["is_disabled"]:
        return await alert(cb, "🚫 This bot is disabled by the platform admin.")
    if not await app.broadcasts.start(bot["id"], bc["id"]):
        return await alert(cb, "⚠️ This broadcast was already started.")
    await app.audit("broadcast.start", "ok", user_id=cb.from_user.id, bot_id=bot["id"])
    cb.data = f"bc:view:{bot['id']}:{bc['id']}"
    await bc_view(cb, app)


@router.callback_query(F.data.startswith(("bc:pause:", "bc:resume:", "bc:cancel:")))
async def bc_control(cb: CallbackQuery, app) -> None:
    bot, bc = await _get(cb, app)
    if not bc:
        return
    action = arg(cb, 1)
    await {"pause": app.broadcasts.pause, "resume": app.broadcasts.resume, "cancel": app.broadcasts.cancel}[action](bc["id"])
    cb.data = f"bc:view:{bot['id']}:{bc['id']}"
    await bc_view(cb, app)


@router.callback_query(F.data.startswith("bc:disc:"))
async def bc_disc(cb: CallbackQuery, app) -> None:
    bot, bc = await _get(cb, app)
    if bc:
        await app.repos.broadcasts.delete_draft(bot["id"], bc["id"])
        await app.repos.media.delete(bot["id"], bc["media_id"])
        cb.data = f"bc:home:{bot['id']}"
        await bc_home(cb, app)
