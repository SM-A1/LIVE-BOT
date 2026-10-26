from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.common import b, kb
from app.bot.ui import DOT, LINE, arg, esc, show

router = Router(name="start")

PICK = {
    "cmd": ("📚 Commands", "cmd:list:{b}:0"),
    "rsp": ("📝 Responses", "rsp:list:{b}:0"),
    "bc": ("📢 Broadcast", "bc:home:{b}"),
    "sec": ("🛡️ Security", "set:sec:{b}"),
    "set": ("⚙️ Settings", "set:open:{b}"),
    "ana": ("📊 Statistics", "ana:open:{b}"),
}


async def show_home(ev, app) -> None:
    u = ev.from_user
    t = await app.repos.bots.totals_owner(u.id)
    hello = f"Welcome back, {esc(u.first_name)}!" if t["bots"] else f"Welcome, {esc(u.first_name)}!"
    text = (f"{LINE}\n🤖 <b>BOT MANAGER</b>\n{LINE}\n\n{hello}\n\nManage your Telegram bots from one place.\n\n"
            f"🤖 My Bots: <b>{t['bots']}</b>\n🟢 Online: <b>{t['online']}</b>\n👥 Total Users: <b>{int(t['users']):,}</b>\n\n{LINE}")
    rows = [[b("➕ Add Bot", "bots:add"), b("🤖 My Bots", "bots:list")],
            [b("📊 Statistics", "stats:all"), b("⚙️ Settings", "pick:set")],
            [b("📚 Commands", "pick:cmd"), b("📝 Responses", "pick:rsp")],
            [b("📢 Broadcast", "pick:bc"), b("🛡️ Security", "pick:sec")],
            [b("❓ Help", "help")]]
    if app.is_platform_owner(u.id):
        rows.append([b("🛠 Owner Panel", "owner:home")])
    from aiogram.types import InlineKeyboardMarkup
    await show(ev, text, InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(m: Message, app) -> None:
    await app.wizard.clear(m.from_user.id)
    await show_home(m, app)


@router.message(Command("cancel"))
async def cmd_cancel(m: Message, app) -> None:
    await app.wizard.clear(m.from_user.id)
    await m.answer("✅ Cancelled.")
    await show_home(m, app)


@router.callback_query(F.data == "home")
async def cb_home(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    await show_home(cb, app)


@router.callback_query(F.data == "noop:page")
async def cb_noop(cb: CallbackQuery) -> None:
    return


HELP = ("❓ <b>Help</b>\n\n"
        "1️⃣ Create a bot with @BotFather and copy its token.\n"
        "2️⃣ Tap <b>➕ Add Bot</b> and send the token.\n"
        "3️⃣ Open <b>🤖 My Bots → Manage</b> to add commands, auto-responses, a welcome message, buttons, "
        "run broadcasts and see analytics.\n\n"
        "🔒 Tokens are encrypted and never shown in full. Your bots and users are visible only to you.\n\n"
        "Commands: /menu · /cancel · /help")


@router.message(Command("help"))
async def cmd_help(m: Message) -> None:
    await m.answer(HELP, reply_markup=kb([], "home"))


@router.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery) -> None:
    await show(cb, HELP, kb([], "home"))


@router.callback_query(F.data.startswith("pick:"))
async def cb_pick(cb: CallbackQuery, app) -> None:
    sec = arg(cb, 1)
    if sec not in PICK:
        return
    title, target = PICK[sec]
    bots = await app.repos.bots.list_owned(cb.from_user.id)
    if not bots:
        await show(cb, f"{title}\n\nYou have no connected bots yet.", kb([[b("➕ Add Bot", "bots:add")]], "home"))
        return
    rows = [[b(f"{DOT[x['status']]} @{x['username']}", target.format(b=x["id"]))] for x in bots]
    await show(cb, f"{title}\n\nChoose a bot:", kb(rows, "home"))


@router.callback_query(F.data == "stats:all")
async def cb_stats_all(cb: CallbackQuery, app) -> None:
    bots = await app.repos.bots.list_owned(cb.from_user.id)
    if not bots:
        await show(cb, "📊 <b>Statistics</b>\n\nNo bots yet.", kb([[b("➕ Add Bot", "bots:add")]], "home"))
        return
    lines = [f"{DOT[x['status']]} @{esc(x['username'])} — 👥 {x['users']:,} · ⚡ {x['commands']} · 💬 {x['responses']}" for x in bots]
    rows = [[b(f"📊 @{x['username']}", f"ana:open:{x['id']}")] for x in bots]
    await show(cb, "📊 <b>Statistics</b>\n\n" + "\n".join(lines), kb(rows, "home"))
