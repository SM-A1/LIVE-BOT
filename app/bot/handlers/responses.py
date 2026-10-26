from __future__ import annotations

import asyncpg
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.common import b, kb, pager
from app.bot.states.wizard import on_input
from app.bot.ui import alert, arg, esc, iarg, own, show
from app.security.validators import clean, valid_regex
from app.services.variables import VARIABLES_HELP

router = Router(name="responses")
PER, MAX_RESPONSES = 8, 200
MODES = {"exact": "🎯 Exact", "contains": "🔍 Contains", "startswith": "▶️ Starts with",
         "endswith": "◀️ Ends with", "regex": "🧩 Regex"}
ORDER = list(MODES)


@router.callback_query(F.data.startswith("rsp:list:"))
async def rsp_list(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    page = max(iarg(cb, 3), 0)
    items = await app.repos.responses.list(bot["id"])
    rows = [[b("➕ New Response", f"rsp:new:{bot['id']}")]]
    rows += [[b(f"{'✅' if r['enabled'] else '⏸'} {r['trigger'][:28]}  ·  {MODES[r['match_mode']].split(' ')[0]}", f"rsp:view:{bot['id']}:{r['id']}")]
             for r in items[page * PER:(page + 1) * PER]]
    pg = pager(f"rsp:list:{bot['id']}", page, len(items), PER)
    if pg:
        rows.append(pg)
    await show(cb, f"📝 <b>Auto Responses — @{esc(bot['username'])}</b>\n\n{len(items)} rule(s). The first matching rule replies.",
               kb(rows, f"bot:open:{bot['id']}"))


async def view_rsp(ev, app, bot, r) -> None:
    i, rid = bot["id"], r["id"]
    text = (f"📝 <b>Auto Response</b>  {'✅ Enabled' if r['enabled'] else '⏸ Disabled'}\n\n"
            f"Trigger: <code>{esc(r['trigger'])}</code>\nMode: {MODES[r['match_mode']]}\n"
            f"Case-insensitive: {'yes' if r['case_insensitive'] else 'no'}\n\nResponse:\n{esc(r['text'][:500])}")
    rows = [[b("✏️ Trigger", f"rsp:set:{i}:{rid}:trig"), b("✏️ Text", f"rsp:set:{i}:{rid}:text")],
            [b("🔁 Match mode", f"rsp:set:{i}:{rid}:mode"), b(f"Aa Case: {'ignore' if r['case_insensitive'] else 'match'}", f"rsp:set:{i}:{rid}:ci")],
            [b("🔘 Buttons", f"btn:open:{i}:r{rid}"), b("⏸ Disable" if r["enabled"] else "▶️ Enable", f"rsp:set:{i}:{rid}:on")],
            [b("🗑 Delete", f"rsp:del:{i}:{rid}")]]
    await show(ev, text, kb(rows, f"rsp:list:{i}:0"))


async def _get(cb, app):
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return None, None
    r = await app.repos.responses.get(bot["id"], iarg(cb, 3))
    if not r:
        await alert(cb, "⚠️ Response not found.")
        return None, None
    return bot, r


@router.callback_query(F.data.startswith("rsp:view:"))
async def rsp_view(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    bot, r = await _get(cb, app)
    if r:
        await view_rsp(cb, app, bot, r)


@router.callback_query(F.data.startswith("rsp:set:"))
async def rsp_set(cb: CallbackQuery, app) -> None:
    bot, r = await _get(cb, app)
    if not r:
        return
    i, rid, f, repo = bot["id"], r["id"], arg(cb, 4), app.repos.responses
    if f == "on":
        await repo.set_field(i, rid, "enabled", not r["enabled"])
    elif f == "ci":
        await repo.set_field(i, rid, "case_insensitive", not r["case_insensitive"])
    elif f == "mode":
        nxt = ORDER[(ORDER.index(r["match_mode"]) + 1) % len(ORDER)]
        if nxt == "regex" and not valid_regex(r["trigger"]):
            nxt = ORDER[0]
        try:
            await repo.set_field(i, rid, "match_mode", nxt)
        except asyncpg.UniqueViolationError:
            return await alert(cb, "A rule with this trigger and mode already exists.")
    elif f in ("trig", "text"):
        await app.wizard.set(cb.from_user.id, "rsp_edit", bid=i, rid=rid, f=f)
        what = "trigger" if f == "trig" else f"response text\nVariables: <code>{esc(VARIABLES_HELP)}</code>"
        return await show(cb, f"✏️ Send the new {what}.", kb([], f"rsp:view:{i}:{rid}"))
    app.bots.invalidate(i)
    await view_rsp(cb, app, bot, await repo.get(i, rid))


@router.callback_query(F.data.startswith("rsp:del:"))
async def rsp_del(cb: CallbackQuery, app) -> None:
    bot, r = await _get(cb, app)
    if r:
        await show(cb, f"🗑 Delete the rule for <code>{esc(r['trigger'])}</code>?",
                   kb([[b("✅ Yes, delete", f"rsp:delok:{bot['id']}:{r['id']}")]], f"rsp:view:{bot['id']}:{r['id']}"))


@router.callback_query(F.data.startswith("rsp:delok:"))
async def rsp_delok(cb: CallbackQuery, app) -> None:
    bot, r = await _get(cb, app)
    if r:
        await app.repos.responses.delete(bot["id"], r["id"])
        app.bots.invalidate(bot["id"])
        cb.data = f"rsp:list:{bot['id']}:0"
        await rsp_list(cb, app)


# --- create ----------------------------------------------------------------------
@router.callback_query(F.data.startswith("rsp:new:"))
async def rsp_new(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    if await app.repos.responses.count(bot["id"]) >= MAX_RESPONSES:
        return await alert(cb, "⚠️ Response limit reached for this bot.")
    await app.wizard.set(cb.from_user.id, "rsp_trigger", bid=bot["id"])
    await show(cb, "➕ <b>New Auto Response</b>\n\nSend the <b>trigger</b> text, e.g. <code>hello</code>.",
               kb([], f"rsp:list:{bot['id']}:0"))


@on_input("rsp_trigger")
async def in_trigger(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    trig = clean(m.text, 200)
    if not bot or not trig:
        return await m.answer("Please send the trigger as text.")
    await app.wizard.set(m.from_user.id, "rsp_mode", bid=bot["id"], trigger=trig)
    rows = [[b(label, f"rsp:mode:{bot['id']}:{k}")] for k, label in MODES.items()]
    await m.answer(f"Trigger: <code>{esc(trig)}</code>\n\nChoose how it should match:", reply_markup=kb(rows, f"rsp:list:{bot['id']}:0"))


@router.callback_query(F.data.startswith("rsp:mode:"))
async def rsp_mode(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    sess = await app.wizard.get(cb.from_user.id)
    mode = arg(cb, 3)
    if not bot or not sess or sess[0] != "rsp_mode" or mode not in MODES or sess[1].get("bid") != bot["id"]:
        return await alert(cb, "⚠️ Session expired. Start again.")
    trig = sess[1]["trigger"]
    if mode == "regex" and not valid_regex(trig):
        return await alert(cb, "❌ That regex is invalid or too slow. Pick another mode or start again.")
    await app.wizard.set(cb.from_user.id, "rsp_text", bid=bot["id"], trigger=trig, mode=mode)
    await show(cb, f"Now send the <b>response text</b>.\nVariables: <code>{esc(VARIABLES_HELP)}</code>", kb([], f"rsp:list:{bot['id']}:0"))


@on_input("rsp_text")
async def in_rsp_text(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    text = clean(m.text, 4000)
    if not bot or not text:
        return await m.answer("Please send the response as text.")
    try:
        r = await app.repos.responses.create(bot["id"], data["trigger"], data["mode"], text)
    except asyncpg.UniqueViolationError:
        await app.wizard.clear(m.from_user.id)
        return await m.answer("❌ A rule with this trigger and mode already exists.")
    await app.wizard.clear(m.from_user.id)
    app.bots.invalidate(bot["id"])
    await view_rsp(m, app, bot, r)


@on_input("rsp_edit")
async def in_rsp_edit(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    r = await app.repos.responses.get(bot["id"], data["rid"]) if bot else None
    val = clean(m.text, 4000 if data["f"] == "text" else 200)
    if not r or not val:
        return await m.answer("Please send text.")
    if data["f"] == "trig":
        if r["match_mode"] == "regex" and not valid_regex(val):
            return await m.answer("❌ Invalid or too slow regex. Try again:")
        try:
            await app.repos.responses.set_field(bot["id"], r["id"], "trigger", val)
        except asyncpg.UniqueViolationError:
            return await m.answer("❌ A rule with this trigger and mode already exists.")
    else:
        await app.repos.responses.set_field(bot["id"], r["id"], "text", val)
    await app.wizard.clear(m.from_user.id)
    app.bots.invalidate(bot["id"])
    await view_rsp(m, app, bot, await app.repos.responses.get(bot["id"], r["id"]))
