from __future__ import annotations

import asyncpg
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import BotCommand, BotCommandScopeDefault, CallbackQuery, Message

from app.bot import media as media_util
from app.bot.childapi import child_bot
from app.bot.keyboards.common import b, kb, pager
from app.bot.states.wizard import on_input
from app.bot.ui import alert, arg, esc, iarg, own, show
from app.security.validators import COMMAND_RE, clean, parse_names
from app.services.variables import VARIABLES_HELP

router = Router(name="commands")
PER = 8
MAX_COMMANDS = 100
TYPES = {"text": "📝 Text", "photo": "🖼 Photo", "video": "🎥 Video", "document": "📄 Document",
         "audio": "🎵 Audio", "voice": "🎙 Voice", "script": "🐍 Python Script"}
SCOPES = ["any", "private", "group"]
SCOPE_LABEL = {"any": "💬 Anywhere", "private": "👤 Private only", "group": "👥 Groups only"}
MEDIA_TYPES = ("photo", "video", "document", "audio", "voice")


@router.callback_query(F.data.startswith("cmd:list:"))
async def cmd_list(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    page = max(iarg(cb, 3), 0)
    cmds = await app.repos.commands.list(bot["id"])
    chunk = cmds[page * PER:(page + 1) * PER]
    rows = [[b("➕ Create Command", f"cmd:new:{bot['id']}")]]
    rows += [[b(f"{'✅' if c['enabled'] else '⏸'} /{c['name']}  ·  {TYPES[c['response_type']].split(' ')[0]}", f"cmd:view:{bot['id']}:{c['id']}")] for c in chunk]
    pg = pager(f"cmd:list:{bot['id']}", page, len(cmds), PER)
    if pg:
        rows.append(pg)
    rows.append([b("🔄 Sync to Telegram menu", f"cmd:sync:{bot['id']}")])
    await show(cb, f"📚 <b>Commands — @{esc(bot['username'])}</b>\n\n{len(cmds)} command(s). Tap one to view, edit or delete it.",
               kb(rows, f"bot:open:{bot['id']}"))


async def view_cmd(ev, app, bot, c) -> None:
    media = await app.repos.media.meta(bot["id"], c["media_id"]) if c["media_id"] else None
    body = esc(c["text"][:300]) or "<i>(empty)</i>"
    if c["response_type"] == "script":
        sc = await app.repos.scripts.get(bot["id"], c["script_id"]) if c["script_id"] else None
        body = f"🐍 Script: <b>{esc(sc['name']) if sc else 'none selected'}</b>"
    elif media:
        body = f"📎 {media['kind']} attached\n{body}"
    text = (f"⚡ <b>/{esc(c['name'])}</b>  {'✅ Enabled' if c['enabled'] else '⏸ Disabled'}\n\n"
            f"Type: {TYPES[c['response_type']]}\nDescription: {esc(c['description']) or '—'}\n"
            f"Aliases: {', '.join('/' + a for a in c['aliases']) or '—'}\nScope: {SCOPE_LABEL[c['scope']]}\n"
            f"Admin only: {'yes' if c['admin_only'] else 'no'}\n\n{body}")
    i, cid = bot["id"], c["id"]
    rows = [[b("✏️ Edit", f"cmd:edit:{i}:{cid}"), b("🔘 Buttons", f"btn:open:{i}:c{cid}")],
            [b("⏸ Disable" if c["enabled"] else "▶️ Enable", f"cmd:set:{i}:{cid}:on"), b("🗑 Delete", f"cmd:del:{i}:{cid}")]]
    await show(ev, text, kb(rows, f"cmd:list:{i}:0"))


async def _get(cb, app):
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return None, None
    c = await app.repos.commands.get(bot["id"], iarg(cb, 3))
    if not c:
        await alert(cb, "⚠️ Command not found.")
        return None, None
    return bot, c


@router.callback_query(F.data.startswith("cmd:view:"))
async def cmd_view(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    bot, c = await _get(cb, app)
    if c:
        await view_cmd(cb, app, bot, c)


@router.callback_query(F.data.startswith("cmd:edit:"))
async def cmd_edit(cb: CallbackQuery, app) -> None:
    bot, c = await _get(cb, app)
    if not c:
        return
    i, cid = bot["id"], c["id"]
    rows = [[b("📝 Description", f"cmd:set:{i}:{cid}:desc"), b("🏷 Aliases", f"cmd:set:{i}:{cid}:alias")],
            [b("📄 Response text", f"cmd:set:{i}:{cid}:text")]]
    if c["response_type"] in MEDIA_TYPES:
        rows.append([b("📎 Replace media", f"cmd:set:{i}:{cid}:media")])
    if c["response_type"] == "script":
        rows.append([b("🐍 Choose script", f"cmd:set:{i}:{cid}:script")])
    rows += [[b(f"🔒 Admin only: {'ON' if c['admin_only'] else 'OFF'}", f"cmd:set:{i}:{cid}:admin"),
              b(SCOPE_LABEL[c["scope"]], f"cmd:set:{i}:{cid}:scope")]]
    await show(cb, f"✏️ <b>Edit /{esc(c['name'])}</b>\n\nVariables: <code>{esc(VARIABLES_HELP)}</code>", kb(rows, f"cmd:view:{i}:{cid}"))


@router.callback_query(F.data.startswith("cmd:set:"))
async def cmd_set(cb: CallbackQuery, app) -> None:
    bot, c = await _get(cb, app)
    if not c:
        return
    i, cid, f = bot["id"], c["id"], arg(cb, 4)
    repo = app.repos.commands
    if f == "on":
        await repo.set_field(i, cid, "enabled", not c["enabled"])
    elif f == "admin":
        await repo.set_field(i, cid, "admin_only", not c["admin_only"])
    elif f == "scope":
        await repo.set_field(i, cid, "scope", SCOPES[(SCOPES.index(c["scope"]) + 1) % 3])
        app.bots.invalidate(i)
        cb.data = f"cmd:edit:{i}:{cid}"
        return await cmd_edit(cb, app)
    elif f == "script":
        scripts = await app.repos.scripts.list(i)
        if not scripts:
            return await alert(cb, "Create a script first (🐍 Scripts in the bot dashboard).")
        rows = [[b(f"🐍 {s['name']}", f"cmd:spk:{i}:{cid}:{s['id']}")] for s in scripts]
        return await show(cb, "🐍 Choose the script this command runs:", kb(rows, f"cmd:edit:{i}:{cid}"))
    elif f in ("desc", "alias", "text", "media"):
        prompts = {"desc": "Send the new <b>description</b> (shown in Telegram's command menu).",
                   "alias": "Send <b>aliases</b> separated by spaces or commas (e.g. <code>hi hey</code>). Send <code>-</code> to clear.",
                   "text": f"Send the new <b>response text</b>.\nVariables: <code>{esc(VARIABLES_HELP)}</code>",
                   "media": "Send the new <b>file</b> (use a caption for the text)."}
        await app.wizard.set(cb.from_user.id, "cmd_edit", bid=i, cid=cid, f=f)
        return await show(cb, "✏️ " + prompts[f], kb([], f"cmd:edit:{i}:{cid}"))
    app.bots.invalidate(i)
    cb.data = f"cmd:view:{i}:{cid}"
    await cmd_view(cb, app)


@router.callback_query(F.data.startswith("cmd:spk:"))
async def cmd_script_pick(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    sc = await app.repos.scripts.get(bot["id"], iarg(cb, 4))
    c = await app.repos.commands.get(bot["id"], iarg(cb, 3))
    if sc and c:
        await app.repos.commands.set_field(bot["id"], c["id"], "script_id", sc["id"])
        app.bots.invalidate(bot["id"])
        await view_cmd(cb, app, bot, await app.repos.commands.get(bot["id"], c["id"]))


@router.callback_query(F.data.startswith("cmd:del:"))
async def cmd_del(cb: CallbackQuery, app) -> None:
    bot, c = await _get(cb, app)
    if c:
        await show(cb, f"🗑 Delete <b>/{esc(c['name'])}</b>?", kb([[b("✅ Yes, delete", f"cmd:delok:{bot['id']}:{c['id']}")]], f"cmd:view:{bot['id']}:{c['id']}"))


@router.callback_query(F.data.startswith("cmd:delok:"))
async def cmd_delok(cb: CallbackQuery, app) -> None:
    bot, c = await _get(cb, app)
    if c:
        await app.repos.commands.delete(bot["id"], c["id"])
        await app.repos.media.delete(bot["id"], c["media_id"])
        app.bots.invalidate(bot["id"])
        cb.data = f"cmd:list:{bot['id']}:0"
        await cmd_list(cb, app)


@router.callback_query(F.data.startswith("cmd:sync:"))
async def cmd_sync(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    cmds = [c for c in await app.repos.commands.list(bot["id"]) if c["enabled"] and not c["admin_only"]]
    items = [BotCommand(command=c["name"], description=(c["description"] or c["name"])[:200].ljust(3, ".")) for c in cmds[:100]]
    try:
        tg = await child_bot(app, bot)
        if items:
            await tg.set_my_commands(items, scope=BotCommandScopeDefault())
        else:
            await tg.delete_my_commands()
        await alert(cb, f"✅ {len(items)} command(s) published to Telegram's menu.")
    except TelegramRetryAfter as e:
        await alert(cb, f"⏳ Telegram asks to wait {e.retry_after}s. Try again later.")
    except Exception:
        await alert(cb, "⚠️ Couldn't update the Telegram command menu right now.")


# --- create flow ----------------------------------------------------------------
@router.callback_query(F.data.startswith("cmd:new:"))
async def cmd_new(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    if await app.repos.commands.count(bot["id"]) >= MAX_COMMANDS:
        return await alert(cb, "⚠️ Command limit reached for this bot.")
    await app.wizard.set(cb.from_user.id, "cmd_name", bid=bot["id"])
    await show(cb, "➕ <b>Create Command</b>\n\nSend the command name, e.g. <code>/start</code> or <code>hello</code>.\n"
                   "Letters, digits and underscores only (max 32).", kb([], f"cmd:list:{bot['id']}:0"))


@on_input("cmd_name")
async def in_cmd_name(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    if not bot:
        return
    names = parse_names(m.text or "")
    if not names or len(names) != 1:
        return await m.answer("❌ Invalid name. Use letters, digits and underscores only (max 32). Try again:")
    if names[0] in await app.repos.commands.taken_names(bot["id"]):
        return await m.answer("❌ That command (or alias) already exists. Send a different name:")
    await app.wizard.set(m.from_user.id, "cmd_type", bid=bot["id"], name=names[0])
    rows = [[b(label, f"cmd:type:{bot['id']}:{k}")] for k, label in TYPES.items()]
    await m.answer(f"⚡ <b>/{esc(names[0])}</b>\n\nChoose the response type:", reply_markup=kb(rows, f"cmd:list:{bot['id']}:0"))


@router.callback_query(F.data.startswith("cmd:type:"))
async def cmd_type(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    sess = await app.wizard.get(cb.from_user.id)
    t = arg(cb, 3)
    if not bot or not sess or sess[0] != "cmd_type" or sess[1].get("bid") != bot["id"] or t not in TYPES:
        return await alert(cb, "⚠️ Session expired. Start again.")
    name = sess[1]["name"]
    back = f"cmd:list:{bot['id']}:0"
    if t == "text":
        await app.wizard.set(cb.from_user.id, "cmd_text", bid=bot["id"], name=name)
        await show(cb, f"📝 Send the response text for <b>/{esc(name)}</b>.\nVariables: <code>{esc(VARIABLES_HELP)}</code>", kb([], back))
    elif t == "script":
        scripts = await app.repos.scripts.list(bot["id"])
        if not scripts:
            return await show(cb, "🐍 You have no scripts yet. Create one under <b>Scripts</b> first, then create this command again.",
                              kb([[b("🐍 Scripts", f"scr:list:{bot['id']}")]], back))
        rows = [[b(f"🐍 {s['name']}", f"cmd:spick:{bot['id']}:{s['id']}")] for s in scripts]
        await show(cb, "🐍 Choose the script:", kb(rows, back))
    else:
        await app.wizard.set(cb.from_user.id, "cmd_media", bid=bot["id"], name=name, t=t)
        await show(cb, f"{TYPES[t]}\n\nSend the file now. Add a caption to use it as the message text.", kb([], back))


@router.callback_query(F.data.startswith("cmd:spick:"))
async def cmd_spick(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    sess = await app.wizard.get(cb.from_user.id)
    sc = await app.repos.scripts.get(bot["id"], iarg(cb, 3)) if bot else None
    if not (bot and sc and sess and sess[0] == "cmd_type" and sess[1].get("bid") == bot["id"]):
        return await alert(cb, "⚠️ Session expired. Start again.")
    await _create(cb, app, bot, sess[1]["name"], "script", script_id=sc["id"])


async def _create(ev, app, bot, name, rtype, text="", media_id=None, script_id=None) -> None:
    try:
        c = await app.repos.commands.create(bot["id"], name, rtype, text, media_id, script_id)
    except asyncpg.UniqueViolationError:
        return await alert(ev, "❌ That command already exists.")
    await app.wizard.clear(ev.from_user.id)
    app.bots.invalidate(bot["id"])
    await view_cmd(ev, app, bot, c)


@on_input("cmd_text")
async def in_cmd_text(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    text = clean(m.text, 4000)
    if not bot or not text:
        return await m.answer("Please send the response as text.")
    await _create(m, app, bot, data["name"], "text", text)


@on_input("cmd_media")
async def in_cmd_media(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    if not bot:
        return
    mid, err = await media_util.store(app, m, bot["id"], (data["t"],))
    if err:
        return await m.answer(f"❌ {err}")
    await _create(m, app, bot, data["name"], data["t"], clean(m.caption, 1000), mid)


@on_input("cmd_edit")
async def in_cmd_edit(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    c = await app.repos.commands.get(bot["id"], data["cid"]) if bot else None
    if not c:
        return
    f, repo = data["f"], app.repos.commands
    if f == "desc":
        await repo.set_field(bot["id"], c["id"], "description", clean(m.text, 200))
    elif f == "text":
        t = clean(m.text, 4000)
        if not t:
            return await m.answer("Please send text.")
        await repo.set_field(bot["id"], c["id"], "text", t)
    elif f == "alias":
        raw = (m.text or "").strip()
        names = [] if raw == "-" else parse_names(raw)
        if names is None:
            return await m.answer("❌ Aliases may contain letters, digits and underscores only. Try again:")
        if set(names) & (await repo.taken_names(bot["id"], c["id"]) | {c["name"]}):
            return await m.answer("❌ One of those names is already used. Try again:")
        await repo.set_field(bot["id"], c["id"], "aliases", names[:10])
    elif f == "media":
        mid, err = await media_util.store(app, m, bot["id"], (c["response_type"],))
        if err:
            return await m.answer(f"❌ {err}")
        await app.repos.media.delete(bot["id"], c["media_id"])
        await repo.set_field(bot["id"], c["id"], "media_id", mid)
        if m.caption:
            await repo.set_field(bot["id"], c["id"], "text", clean(m.caption, 1000))
    await app.wizard.clear(m.from_user.id)
    app.bots.invalidate(bot["id"])
    await view_cmd(m, app, bot, await repo.get(bot["id"], c["id"]))
