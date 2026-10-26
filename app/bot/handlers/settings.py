from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import CallbackQuery, Message

from app.bot.childapi import child_bot
from app.bot.keyboards.common import b, kb
from app.bot.states.wizard import on_input
from app.bot.ui import STATUS, alert, arg, esc, iarg, own, show
from app.manager.attribution import DEFAULT as ATTR_DEFAULT, build_text
from app.security.validators import clean

router = Router(name="settings")


def yn(v) -> str:
    return "✅ ON" if v else "❌ OFF"


SECTION = {"maintenance_mode": "beh", "group_mode": "beh", "attribution_enabled": "attr",
           "logging_enabled": "adv", "developer_mode": "adv"}


@router.callback_query(F.data.startswith("set:open:"))
async def set_open(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    i = bot["id"]
    rows = [[b("🧾 General", f"set:gen:{i}"), b("🎛 Behaviour", f"set:beh:{i}")],
            [b("🔐 Security", f"set:sec:{i}"), b("🛠 Advanced", f"set:adv:{i}")],
            [b("🏷 Attribution", f"set:attr:{i}")]]
    await show(cb, f"⚙️ <b>Settings — @{esc(bot['username'])}</b>", kb(rows, f"bot:open:{i}"))


@router.callback_query(F.data.startswith("set:gen:"))
async def set_gen(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    i = bot["id"]
    name = desc = about = "—"
    try:
        tg = await child_bot(app, bot)
        name = (await tg.get_my_name()).name or "—"
        desc = (await tg.get_my_description()).description or "—"
        about = (await tg.get_my_short_description()).short_description or "—"
    except Exception:
        pass
    rows = [[b("✏️ Name", f"set:edit:{i}:name"), b("✏️ Description", f"set:edit:{i}:desc")],
            [b("✏️ About", f"set:edit:{i}:about"), b("📚 Commands", f"cmd:list:{i}:0")]]
    await show(cb, f"🧾 <b>General — @{esc(bot['username'])}</b>\n\nName: {esc(name)}\nDescription: {esc(desc[:200])}\nAbout: {esc(about)}\n\n"
                   f"These are published to Telegram through your bot's token.", kb(rows, f"set:open:{i}"))


@router.callback_query(F.data.startswith("set:beh:"))
async def set_beh(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    i, s = bot["id"], await app.repos.bots.settings(bot["id"])
    rows = [[b(f"🛠 Maintenance: {yn(s['maintenance_mode'])}", f"set:tog:{i}:maintenance_mode")],
            [b(f"👥 Group mode: {yn(s['group_mode'])}", f"set:tog:{i}:group_mode")],
            [b("✏️ Maintenance text", f"set:edit:{i}:maint")],
            [b("👋 Welcome", f"wel:open:{i}"), b("📝 Auto responses", f"rsp:list:{i}:0")]]
    await show(cb, "🎛 <b>Behaviour</b>\n\nMaintenance: only you and admins get answers.\nGroup mode OFF: the bot ignores group chats.", kb(rows, f"set:open:{i}"))


@router.callback_query(F.data.startswith("set:sec:"))
async def set_sec(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    i = bot["id"]
    admins = await app.repos.bots.admins(i)
    st = await app.repos.botusers.stats(i)
    rows = [[b("➕ Add admin", f"set:aadd:{i}")]] + [[b(f"➖ {a}", f"set:adel:{i}:{a}")] for a in admins]
    rows.append([b(f"🚫 Blocked users ({st['banned']})", f"usr:list:{i}:0")])
    await show(cb, f"🔐 <b>Security — @{esc(bot['username'])}</b>\n\nOwner ID: <code>{bot['owner_id']}</code>\n"
                   f"Admin IDs: {', '.join(f'<code>{a}</code>' for a in admins) or '—'}\nBanned: {st['banned']} · Blocked the bot: {st['blocked']}\n\n"
                   f"Admins can use admin-only commands and bypass maintenance mode.", kb(rows, f"bot:open:{i}"))


@router.callback_query(F.data.startswith("set:aadd:"))
async def set_aadd(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if bot:
        await app.wizard.set(cb.from_user.id, "sec_admin", bid=bot["id"])
        await show(cb, "Send the numeric Telegram <b>user ID</b> of the new admin.", kb([], f"set:sec:{bot['id']}"))


@router.callback_query(F.data.startswith("set:adel:"))
async def set_adel(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if bot:
        await app.repos.bots.remove_admin(bot["id"], iarg(cb, 3))
        app.bots.invalidate(bot["id"])
        cb.data = f"set:sec:{bot['id']}"
        await set_sec(cb, app)


@on_input("sec_admin")
async def in_admin(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    raw = (m.text or "").strip()
    if not bot or not raw.isdigit() or len(raw) > 15:
        return await m.answer("❌ Send a numeric user ID.")
    if len(await app.repos.bots.admins(bot["id"])) >= 20:
        return await m.answer("⚠️ Admin limit reached.")
    await app.repos.bots.add_admin(bot["id"], int(raw))
    await app.wizard.clear(m.from_user.id)
    app.bots.invalidate(bot["id"])
    await m.answer("✅ Admin added.", reply_markup=kb([], f"set:sec:{bot['id']}"))


@router.callback_query(F.data.startswith("set:adv:"))
async def set_adv(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    i, s = bot["id"], await app.repos.bots.settings(bot["id"])
    err = f"\n⚠️ {esc(bot['last_error'])}" if bot["last_error"] else ""
    rows = [[b(f"Mode: {'📡 Webhook' if s['update_mode'] == 'webhook' else '🔄 Polling'}", f"set:mode:{i}:{'polling' if s['update_mode'] == 'webhook' else 'webhook'}")],
            [b(f"📜 Logging: {yn(s['logging_enabled'])}", f"set:tog:{i}:logging_enabled")],
            [b(f"🧑‍💻 Developer mode: {yn(s['developer_mode'])}", f"set:tog:{i}:developer_mode")],
            [b("📜 Recent logs", f"set:logs:{i}"), b("🔄 Restart", f"bot:restart:{i}")]]
    await show(cb, f"🛠 <b>Advanced</b>\n\nStatus: {STATUS[bot['status']]}{err}\n\nWebhook needs a public HTTPS URL configured by the platform owner. "
                   f"Developer mode shows script errors to you and your admins.", kb(rows, f"set:open:{i}"))


@router.callback_query(F.data.startswith("set:mode:"))
async def set_mode(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    mode = arg(cb, 3)
    if not bot or mode not in ("polling", "webhook"):
        return
    if mode == "webhook" and not app.settings.webhook_base_url:
        return await alert(cb, "Webhook mode isn't available: the platform has no WEBHOOK_BASE_URL configured.")
    await app.repos.bots.set_setting(bot["id"], "update_mode", mode)
    await app.bots.restart_bot(bot["id"])
    cb.data = f"set:adv:{bot['id']}"
    await set_adv(cb, app)


@router.callback_query(F.data.startswith("set:logs:"))
async def set_logs(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    rows = await app.repos.platform.recent_logs(12, bot_id=bot["id"])
    txt = "\n".join(f"{r['ts']:%m-%d %H:%M} {esc(r['action'])} {esc(r['status'])} {esc(r['error_code'] or '')}" for r in rows) or "No events yet."
    await show(cb, f"📜 <b>Recent events</b>\n\n<pre>{txt}</pre>", kb([], f"set:adv:{bot['id']}"))


@router.callback_query(F.data.startswith("set:tog:"))
async def set_tog(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    f = arg(cb, 3)
    if not bot or f not in SECTION:
        return
    s = await app.repos.bots.settings(bot["id"])
    await app.repos.bots.set_setting(bot["id"], f, not s[f])
    app.bots.invalidate(bot["id"])
    cb.data = f"set:{SECTION[f]}:{bot['id']}"
    await {"beh": set_beh, "adv": set_adv, "attr": set_attr}[SECTION[f]](cb, app)


@router.callback_query(F.data.startswith("set:attr:"))
async def set_attr(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    i, s = bot["id"], await app.repos.bots.settings(bot["id"])
    allow = (await app.features())["custom_attribution"]
    ident = await app.identity.get()
    shown = build_text(ident, s, allow) or "(unavailable — manager username not detected)"
    rows = [[b("✅ Enable" if not s["attribution_enabled"] else "❌ Disable", f"set:tog:{i}:attribution_enabled")]]
    if allow:
        rows.append([b("✏️ Custom text", f"set:edit:{i}:attr"), b("↩️ Default", f"set:edit:{i}:attrdef")])
    await show(cb, f"🏷 <b>Attribution</b>\n\nStatus: {yn(s['attribution_enabled'])}\nText: <i>{esc(shown)}</i>\n\n"
                   f"The username is detected automatically from Telegram. Custom text "
                   f"{'is allowed (use {MANAGER_BOT_USERNAME})' if allow else 'is disabled by the platform owner'}.", kb(rows, f"set:open:{i}"))


@router.callback_query(F.data.startswith("set:edit:"))
async def set_edit(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    f = arg(cb, 3)
    if not bot:
        return
    i = bot["id"]
    if f == "attrdef":
        await app.repos.bots.set_setting(i, "attribution_text", None)
        app.bots.invalidate(i)
        cb.data = f"set:attr:{i}"
        return await set_attr(cb, app)
    if f == "attr" and not (await app.features())["custom_attribution"]:
        return await alert(cb, "Custom attribution is disabled by the platform owner.")
    prompts = {"name": "Send the new bot <b>name</b> (max 64).", "desc": "Send the new <b>description</b> (max 512).",
               "about": "Send the new <b>about</b> text (max 120).", "maint": "Send the <b>maintenance message</b>.",
               "attr": f"Send the custom attribution text. Include <code>{{MANAGER_BOT_USERNAME}}</code>. Default: <i>{esc(ATTR_DEFAULT)}</i>"}
    if f not in prompts:
        return
    back = {"name": "gen", "desc": "gen", "about": "gen", "maint": "beh", "attr": "attr"}[f]
    await app.wizard.set(cb.from_user.id, "set_edit", bid=i, f=f)
    await show(cb, "✏️ " + prompts[f], kb([], f"set:{back}:{i}"))


@on_input("set_edit")
async def in_set_edit(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    f = data["f"]
    limits = {"name": 64, "desc": 512, "about": 120, "maint": 500, "attr": 300}
    val = clean(m.text, limits[f])
    if not bot or not val:
        return await m.answer("Please send text.")
    try:
        if f in ("name", "desc", "about"):
            tg = await child_bot(app, bot)
            if f == "name":
                await tg.set_my_name(name=val)
                await app.repos.bots.set_name(bot["id"], val)
            elif f == "desc":
                await tg.set_my_description(description=val)
            else:
                await tg.set_my_short_description(short_description=val)
        elif f == "maint":
            await app.repos.bots.set_setting(bot["id"], "maintenance_text", val)
        elif f == "attr":
            if not (await app.features())["custom_attribution"]:
                return await m.answer("Custom attribution is disabled.")
            await app.repos.bots.set_setting(bot["id"], "attribution_text", val)
    except TelegramRetryAfter as e:
        return await m.answer(f"⏳ Telegram asks you to wait {e.retry_after}s before changing this again.")
    except TelegramBadRequest:
        return await m.answer("❌ Telegram rejected that value. Try something else.")
    await app.wizard.clear(m.from_user.id)
    app.bots.invalidate(bot["id"])
    await m.answer("✅ Saved.", reply_markup=kb([], f"set:open:{bot['id']}"))
