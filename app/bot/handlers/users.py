from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.common import b, kb, pager
from app.bot.states.wizard import on_input
from app.bot.ui import alert, arg, esc, iarg, own, show
from app.security.validators import clean
from app.services.analytics import render_dashboard

router = Router(name="users")
PER = 8


def label(u) -> str:
    flag = "🚫 " if u["is_banned"] else ("⛔ " if u["is_blocked"] else "")
    return f"{flag}{(u['first_name'] or 'User')[:18]}" + (f" @{u['username']}" if u["username"] else "") + f" · {u['user_id']}"


@router.callback_query(F.data.startswith("usr:list:"))
async def usr_list(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    page = max(iarg(cb, 3), 0)
    total = await app.repos.botusers.count(bot["id"])
    users = await app.repos.botusers.page(bot["id"], page * PER, PER)
    rows = [[b("🔍 Search", f"usr:find:{bot['id']}"), b("📊 User statistics", f"ana:open:{bot['id']}")]]
    rows += [[b(label(u), f"usr:view:{bot['id']}:{u['user_id']}")] for u in users]
    pg = pager(f"usr:list:{bot['id']}", page, total, PER)
    if pg:
        rows.append(pg)
    await show(cb, f"👥 <b>Users — @{esc(bot['username'])}</b>\n\n{total:,} user(s), most recently active first.", kb(rows, f"bot:open:{bot['id']}"))


async def view_user(ev, app, bot, u) -> None:
    status = "🚫 Banned" if u["is_banned"] else ("⛔ Blocked the bot" if u["is_blocked"] else "✅ Active")
    text = (f"👤 <b>{esc(u['first_name'])} {esc(u['last_name'] or '')}</b>\n\n🆔 ID: <code>{u['user_id']}</code>\n"
            f"Username: {'@' + esc(u['username']) if u['username'] else '—'}\n"
            f"First seen: {u['first_seen']:%Y-%m-%d %H:%M}\nLast active: {u['last_active']:%Y-%m-%d %H:%M}\n"
            f"💬 Messages: {u['message_count']:,}\nStatus: {status}")
    act = b("✅ Unban", f"usr:unban:{bot['id']}:{u['user_id']}") if u["is_banned"] else b("🚫 Ban", f"usr:ban:{bot['id']}:{u['user_id']}")
    await show(ev, text, kb([[act]], f"usr:list:{bot['id']}:0"))


async def _user(cb, app):
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return None, None
    u = await app.repos.botusers.get(bot["id"], iarg(cb, 3))
    if not u:
        await alert(cb, "⚠️ User not found.")
        return None, None
    return bot, u


@router.callback_query(F.data.startswith("usr:view:"))
async def usr_view(cb: CallbackQuery, app) -> None:
    bot, u = await _user(cb, app)
    if u:
        await view_user(cb, app, bot, u)


@router.callback_query(F.data.startswith(("usr:ban:", "usr:unban:")))
async def usr_ban(cb: CallbackQuery, app) -> None:
    bot, u = await _user(cb, app)
    if not u:
        return
    if u["user_id"] == bot["owner_id"]:
        return await alert(cb, "You can't ban yourself.")
    await app.repos.botusers.set_banned(bot["id"], u["user_id"], arg(cb, 1) == "ban")
    app.bots.invalidate(bot["id"])
    await view_user(cb, app, bot, await app.repos.botusers.get(bot["id"], u["user_id"]))


@router.callback_query(F.data.startswith("usr:find:"))
async def usr_find(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if bot:
        await app.wizard.set(cb.from_user.id, "usr_search", bid=bot["id"])
        await show(cb, "🔍 Send a user ID, @username or part of a name.", kb([], f"usr:list:{bot['id']}:0"))


@on_input("usr_search")
async def in_search(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    q = clean(m.text, 64)
    if not bot or not q:
        return await m.answer("Please send text to search for.")
    users = await app.repos.botusers.page(bot["id"], 0, 10, q)
    await app.wizard.clear(m.from_user.id)
    rows = [[b(label(u), f"usr:view:{bot['id']}:{u['user_id']}")] for u in users]
    await m.answer(f"🔍 <b>{len(users)} result(s)</b> for <code>{esc(q)}</code>", reply_markup=kb(rows, f"usr:list:{bot['id']}:0"))


@router.callback_query(F.data.startswith("ana:open:"))
async def ana_open(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if bot:
        text = await render_dashboard(app.repos, bot)
        await show(cb, text, kb([[b("🔄 Refresh", f"ana:open:{bot['id']}"), b("👥 Users", f"usr:list:{bot['id']}:0")]], f"bot:open:{bot['id']}"))
