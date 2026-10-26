from __future__ import annotations

import ast
import re

import asyncpg
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.common import b, kb
from app.bot.states.wizard import on_input
from app.bot.ui import alert, arg, esc, iarg, own, show
from app.security.validators import clean
from app.workers.script_runner import ScriptError, validate

router = Router(name="scripts")
MAX_SCRIPTS = 20
EXAMPLE = ("ctx.reply(f\"Hello {user['first_name']}! You sent: {ctx.args or 'nothing'}\")")


def parse_code(raw: str) -> str:
    raw = (raw or "").strip()
    m = re.match(r"^```(?:python|py)?\n?(.*?)```$", raw, re.S)
    return (m.group(1) if m else raw).strip()


def check(code: str) -> str | None:
    if not code or len(code) > 20000:
        return "Script must be 1–20000 characters."
    try:
        validate(ast.parse(code))
    except SyntaxError as e:
        return f"SyntaxError on line {e.lineno}: {e.msg}"
    except ScriptError as e:
        return str(e)
    return None


@router.callback_query(F.data.startswith("scr:list:"))
async def scr_list(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    items = await app.repos.scripts.list(bot["id"])
    on = (await app.features())["scripts"]
    note = "" if on else "\n\n⚠️ Python scripts are currently <b>disabled by the platform owner</b>; you can prepare scripts but they will not run."
    rows = [[b("➕ New Script", f"scr:new:{bot['id']}")]]
    rows += [[b(f"{'✅' if s['enabled'] else '⏸'} {s['name']}", f"scr:view:{bot['id']}:{s['id']}")] for s in items]
    await show(cb, f"🐍 <b>Python Scripts — @{esc(bot['username'])}</b>\n\nScripts run in an isolated, resource-limited worker "
                   f"and attach to a command (Commands → Create → 🐍 Python Script).{note}", kb(rows, f"bot:open:{bot['id']}"))


async def _get(cb, app):
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return None, None
    s = await app.repos.scripts.get(bot["id"], iarg(cb, 3))
    if not s:
        await alert(cb, "⚠️ Script not found.")
        return None, None
    return bot, s


async def view_script(ev, app, bot, s) -> None:
    i, sid = bot["id"], s["id"]
    err = f"\n\n⚠️ Last error: {esc(s['last_error'])}" if s["last_error"] else ""
    text = (f"🐍 <b>{esc(s['name'])}</b>  {'✅ Enabled' if s['enabled'] else '⏸ Disabled'}{err}\n\n<pre>{esc(s['code'][:900])}</pre>")
    rows = [[b("✏️ Replace code", f"scr:code:{i}:{sid}"), b("⏸ Disable" if s["enabled"] else "▶️ Enable", f"scr:tog:{i}:{sid}")],
            [b("🗑 Delete", f"scr:del:{i}:{sid}")]]
    await show(ev, text, kb(rows, f"scr:list:{i}"))


@router.callback_query(F.data.startswith("scr:view:"))
async def scr_view(cb: CallbackQuery, app) -> None:
    bot, s = await _get(cb, app)
    if s:
        await view_script(cb, app, bot, s)


@router.callback_query(F.data.startswith("scr:tog:"))
async def scr_tog(cb: CallbackQuery, app) -> None:
    bot, s = await _get(cb, app)
    if s:
        await app.repos.scripts.set_field(bot["id"], s["id"], "enabled", not s["enabled"])
        await view_script(cb, app, bot, await app.repos.scripts.get(bot["id"], s["id"]))


@router.callback_query(F.data.startswith("scr:del:"))
async def scr_del(cb: CallbackQuery, app) -> None:
    bot, s = await _get(cb, app)
    if s:
        await show(cb, f"🗑 Delete script <b>{esc(s['name'])}</b>? Commands using it will stop working.",
                   kb([[b("✅ Yes, delete", f"scr:delok:{bot['id']}:{s['id']}")]], f"scr:view:{bot['id']}:{s['id']}"))


@router.callback_query(F.data.startswith("scr:delok:"))
async def scr_delok(cb: CallbackQuery, app) -> None:
    bot, s = await _get(cb, app)
    if s:
        await app.repos.scripts.delete(bot["id"], s["id"])
        app.bots.invalidate(bot["id"])
        cb.data = f"scr:list:{bot['id']}"
        await scr_list(cb, app)


@router.callback_query(F.data.startswith("scr:new:"))
async def scr_new(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    if await app.repos.scripts.count(bot["id"]) >= MAX_SCRIPTS:
        return await alert(cb, "⚠️ Script limit reached.")
    await app.wizard.set(cb.from_user.id, "scr_name", bid=bot["id"])
    await show(cb, "🐍 Send a <b>name</b> for the script (max 40 chars).", kb([], f"scr:list:{bot['id']}"))


@on_input("scr_name")
async def in_name(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    name = clean(m.text, 40)
    if not bot or not name:
        return await m.answer("Please send a name.")
    await app.wizard.set(m.from_user.id, "scr_code", bid=bot["id"], name=name, sid=None)
    await m.answer(await _code_help())


async def _code_help() -> str:
    return ("Now send the <b>Python code</b>.\n\nAvailable: <code>ctx.args</code>, <code>ctx.text</code>, <code>user</code>, "
            "<code>chat</code>, <code>ctx.is_admin</code>, <code>ctx.reply(text)</code>, "
            "<code>ctx.reply_buttons(text, [[(label, https_url)]])</code>.\nAllowed imports: json, math, random, re, time, "
            "datetime, collections, itertools, functools, decimal, statistics, textwrap, hashlib, base64, unicodedata.\n"
            "No files, network, <code>open</code>, <code>eval</code> or underscore attributes. Limit: 3 s, 256 MB.\n\n"
            f"Example:\n<pre>{esc(EXAMPLE)}</pre>")


@router.callback_query(F.data.startswith("scr:code:"))
async def scr_code(cb: CallbackQuery, app) -> None:
    bot, s = await _get(cb, app)
    if s:
        await app.wizard.set(cb.from_user.id, "scr_code", bid=bot["id"], name=s["name"], sid=s["id"])
        await show(cb, await _code_help(), kb([], f"scr:view:{bot['id']}:{s['id']}"))


@on_input("scr_code")
async def in_code(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    code = parse_code(m.text)
    if not bot:
        return
    if (err := check(code)):
        return await m.answer(f"❌ {esc(err)}\n\nFix it and send the code again.")
    try:
        if data.get("sid"):
            await app.repos.scripts.set_field(bot["id"], data["sid"], "code", code)
            s = await app.repos.scripts.get(bot["id"], data["sid"])
        else:
            s = await app.repos.scripts.create(bot["id"], data["name"], code)
    except asyncpg.UniqueViolationError:
        await app.wizard.clear(m.from_user.id)
        return await m.answer("❌ A script with this name already exists.")
    await app.wizard.clear(m.from_user.id)
    await view_script(m, app, bot, s)
