from __future__ import annotations

import asyncio

import asyncpg
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.common import b, kb
from app.bot.states.wizard import on_input
from app.bot.ui import DOT, STATUS, alert, esc, iarg, own, show
from app.manager.attribution import send_attribution
from app.manager.token_validator import TokenCheckUnavailable, validate_token

router = Router(name="bots")


@router.callback_query(F.data == "bots:list")
async def bots_list(cb: CallbackQuery, app) -> None:
    bots = await app.repos.bots.list_owned(cb.from_user.id)
    if not bots:
        await show(cb, "🤖 <b>My Bots</b>\n\nYou haven't connected any bots yet.", kb([[b("➕ Add Bot", "bots:add")]], "home"))
        return
    text = "🤖 <b>My Bots</b>\n\n" + "\n\n".join(
        f"🤖 <b>@{esc(x['username'])}</b>\n{STATUS[x['status']]}\n👥 Users: {x['users']:,}\n⚡ Commands: {x['commands']}"
        for x in bots)
    rows = []
    for x in bots:
        i = x["id"]
        rows += [[b(f"⚙️ Manage @{x['username']}", f"bot:open:{i}")],
                 [b("📊 Statistics", f"ana:open:{i}"), b("📚 Commands", f"cmd:list:{i}:0"), b("📝 Responses", f"rsp:list:{i}:0")],
                 [b("🔘 Buttons", f"btn:menu:{i}"), b("⚙️ Settings", f"set:open:{i}"), b("🗑 Remove", f"bot:rm:{i}")]]
    await show(cb, text, kb(rows, "home"))


@router.callback_query(F.data.startswith("bot:open:"))
async def bot_open(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    bot = await app.repos.bots.dashboard(iarg(cb, 2), cb.from_user.id)
    if not bot:
        return await alert(cb, "⚠️ Bot not found.")
    i = bot["id"]
    err = f"\n⚠️ {esc(bot['last_error'])}" if bot["status"] == "error" and bot["last_error"] else ""
    disabled = "\n🚫 Disabled by platform admin" if bot["is_disabled"] else ""
    text = (f"🤖 <b>@{esc(bot['username'])}</b>\n\n{STATUS[bot['status']]}{err}{disabled}\n👥 Users: {bot['users']:,}\n"
            f"⚡ Commands: {bot['commands']}\n💬 Responses: {bot['responses']}")
    rows = [[b("📚 Commands", f"cmd:list:{i}:0"), b("📝 Auto Responses", f"rsp:list:{i}:0")],
            [b("👋 Welcome", f"wel:open:{i}"), b("🔘 Buttons", f"btn:menu:{i}")],
            [b("📢 Broadcast", f"bc:home:{i}"), b("👥 Users", f"usr:list:{i}:0")],
            [b("📊 Analytics", f"ana:open:{i}"), b("⚙️ Settings", f"set:open:{i}")],
            [b("🔐 Security", f"set:sec:{i}"), b("🐍 Scripts", f"scr:list:{i}")],
            [b("🔄 Restart", f"bot:restart:{i}"), b("🗑 Remove", f"bot:rm:{i}")]]
    await show(cb, text, kb(rows, "bots:list"))


@router.callback_query(F.data.startswith("bot:restart:"))
async def bot_restart(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, iarg(cb, 2))
    if not bot:
        return
    if bot["is_disabled"]:
        return await alert(cb, "🚫 This bot was disabled by the platform admin.")
    await cb.answer("🔄 Restarting…")
    await app.bots.restart_bot(bot["id"])
    await asyncio.sleep(1.5)
    cb.data = f"bot:open:{bot['id']}"
    await bot_open(cb, app)


@router.callback_query(F.data.startswith("bot:rm:"))
async def bot_rm(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, iarg(cb, 2))
    if bot:
        await show(cb, f"🗑 <b>Remove @{esc(bot['username'])}?</b>\n\nAll its commands, responses, users and analytics will be "
                       f"permanently deleted. Your bot itself on Telegram is not deleted.",
                   kb([[b("✅ Yes, remove", f"bot:rmok:{bot['id']}")]], f"bot:open:{bot['id']}"))


@router.callback_query(F.data.startswith("bot:rmok:"))
async def bot_rmok(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, iarg(cb, 2))
    if not bot:
        return
    await app.bots.stop_bot(bot["id"], delete_webhook=True)
    await app.repos.bots.delete_owned(bot["id"], cb.from_user.id)
    await app.audit("bot.remove", "ok", user_id=cb.from_user.id, bot_id=bot["id"])
    await show(cb, f"✅ @{esc(bot['username'])} was removed.", kb([], "bots:list"))


# --- Add bot flow ---------------------------------------------------------------
@router.callback_query(F.data == "bots:add")
async def bots_add(cb: CallbackQuery, app) -> None:
    uid = cb.from_user.id
    if not (await app.features())["new_bots"] and not app.is_platform_owner(uid):
        return await alert(cb, "🚧 Adding new bots is temporarily disabled.")
    if await app.repos.bots.count_owned(uid) >= await app.limit_for(uid):
        return await alert(cb, "⚠️ You reached your bot limit. Remove a bot first.")
    await app.wizard.set(uid, "add_token")
    await show(cb, "🤖 <b>Add Your Telegram Bot</b>\n\nSend your BotFather bot token below.\n\nExample:\n"
                   "<code>123456789:AAxxxxxxxxxxxxxxxx</code>\n\n🔒 Your message is deleted right after it is read.",
               kb([], "home"))


@on_input("add_token")
async def add_token(m: Message, app, data: dict) -> None:
    uid = m.from_user.id
    token = (m.text or "").strip()
    try:
        await m.delete()  # never leave the token sitting in the chat
    except Exception:
        pass
    back = kb([], "home")
    status = await m.answer("⏳ Validating your token…")
    ident = await app.identity.get()
    try:
        vb = await validate_token(token, app.session, ident.id if ident else None)
    except TokenCheckUnavailable:
        return await status.edit_text("⚠️ Telegram couldn't be reached. Please send the token again in a moment.", reply_markup=back)
    if vb is None:
        return await status.edit_text("❌ <b>Invalid bot token.</b>\n\nPlease check your BotFather token and try again.", reply_markup=back)
    if await app.repos.bots.count_owned(uid) >= await app.limit_for(uid):
        await app.wizard.clear(uid)
        return await status.edit_text("⚠️ You reached your bot limit.", reply_markup=back)

    enc = app.vault.encrypt(token)
    existing = await app.repos.bots.find_by_tg(vb.id)
    if existing and existing["owner_id"] != uid:
        await app.wizard.clear(uid)
        return await status.edit_text("⚠️ This bot is already connected to the platform.", reply_markup=back)
    if existing:
        await app.repos.bots.update_token(existing["id"], uid, enc, vb.username, vb.first_name)
        await app.wizard.clear(uid)
        await app.bots.restart_bot(existing["id"])
        return await status.edit_text(f"🔄 Token updated for @{esc(vb.username)}.",
                                      reply_markup=kb([[b("⚙️ Manage Bot", f"bot:open:{existing['id']}")]], "bots:list"))
    try:
        row = await app.repos.bots.create(uid, vb.id, vb.username, vb.first_name, enc)
    except asyncpg.UniqueViolationError:
        await app.wizard.clear(uid)
        return await status.edit_text("⚠️ This bot is already connected to the platform.", reply_markup=back)
    await app.wizard.clear(uid)
    rt = await app.bots.start_bot(row["id"])
    for _ in range(10):  # wait briefly for the first successful poll
        if rt and rt.status in ("online", "error"):
            break
        await asyncio.sleep(0.5)
    live = rt.status if rt else "offline"

    # Attribution through the NEW bot's token. Best effort: it can never fail the connection.
    sent = False
    if rt:
        sent = await send_attribution(app, rt.bot, uid, row["id"])
        if sent:
            await app.repos.bots.set_setting(row["id"], "attribution_pending", False)
            app.bots.invalidate(row["id"])
    await app.audit("bot.connect", "ok", user_id=uid, bot_id=row["id"])

    ident = await app.identity.get()
    powered = f"\n\n⚡ Powered by @{esc(ident.username)}" if ident and ident.username else ""
    hint = "" if sent or live != "online" else ""
    if not sent:
        hint = f"\n\n💡 Open @{esc(vb.username)} and press Start once so the bot can message you."
    await status.edit_text(
        f"✅ <b>Bot Connected Successfully!</b>\n\n🤖 Bot: @{esc(vb.username)}\n🆔 ID: <code>{vb.id}</code>\n"
        f"{DOT.get(live, '🟡')} Status: {'Connected' if live == 'online' else STATUS[live]}\n\n"
        f"Your bot is now ready to configure.{powered}{hint}",
        reply_markup=kb([[b("⚙️ Manage Bot", f"bot:open:{row['id']}")]], "bots:list"))
