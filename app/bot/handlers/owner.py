from __future__ import annotations

import asyncio
import os
import resource

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, Filter
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.common import b, kb, pager
from app.bot.states.wizard import on_input
from app.bot.ui import DOT, STATUS, alert, arg, esc, iarg, show
from app.security.validators import clean

router = Router(name="owner")
PER = 8


class OwnerOnly(Filter):
    async def __call__(self, ev, app) -> bool:
        return app.is_platform_owner(ev.from_user.id)


router.callback_query.filter(OwnerOnly())
router.message.filter(OwnerOnly())


async def home_view(ev, app) -> None:
    t = await app.repos.bots.totals()
    text = (f"🛠 <b>Owner Panel</b>\n\n👥 Platform users: <b>{t['users']:,}</b>\n🤖 Bots: <b>{t['bots']:,}</b> "
            f"(🟢 {t['online']} · ⚠️ {t['errors']})\n👤 End users across bots: <b>{t['end_users']:,}</b>")
    rows = [[b("🤖 Bots", "owner:bots:0"), b("👥 Users", "owner:users:0")],
            [b("🚫 Ban/unban by ID", "owner:ban"), b("🔢 Set bot limit", "owner:limit")],
            [b("📜 Logs", "owner:logs"), b("❗ Errors", "owner:errs")],
            [b("📣 Announcement", "owner:cast"), b("🎛 Features", "owner:feat")],
            [b("📟 Resources", "owner:res")]]
    await show(ev, text, kb(rows, "home"))


@router.message(Command("owner"))
async def cmd_owner(m: Message, app) -> None:
    await home_view(m, app)


@router.callback_query(F.data == "owner:home")
async def cb_home(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    await home_view(cb, app)


@router.callback_query(F.data.startswith("owner:bots:"))
async def bots(cb: CallbackQuery, app) -> None:
    page = max(iarg(cb, 2), 0)
    t = await app.repos.bots.totals()
    items = await app.repos.bots.page_all(page * PER, PER)
    rows = [[b(f"{DOT[x['status']]} @{x['username']}{' 🚫' if x['is_disabled'] else ''}", f"owner:bot:{x['id']}")] for x in items]
    pg = pager("owner:bots", page, t["bots"], PER)
    if pg:
        rows.append(pg)
    await show(cb, "🤖 <b>All bots</b>", kb(rows, "owner:home"))


@router.callback_query(F.data.startswith("owner:bot:"))
async def bot_view(cb: CallbackQuery, app) -> None:
    x = await app.repos.bots.get_any(iarg(cb, 2))
    if not x:
        return await alert(cb, "Not found.")
    n = await app.repos.botusers.count(x["id"])
    text = (f"🤖 <b>@{esc(x['username'])}</b>\nID: <code>{x['id']}</code> · Owner: <code>{x['owner_id']}</code>\n"
            f"{STATUS[x['status']]}{' · 🚫 disabled' if x['is_disabled'] else ''}\n👥 Users: {n:,}\nLast error: {esc(x['last_error']) or '—'}")
    act = b("✅ Enable", f"owner:en:{x['id']}") if x["is_disabled"] else b("🚫 Disable", f"owner:dis:{x['id']}")
    await show(cb, text, kb([[act]], "owner:bots:0"))


@router.callback_query(F.data.startswith(("owner:dis:", "owner:en:")))
async def toggle_bot(cb: CallbackQuery, app) -> None:
    bid, disable = iarg(cb, 2), arg(cb, 1) == "dis"
    x = await app.repos.bots.get_any(bid)
    if not x:
        return
    await app.repos.bots.set_disabled(bid, disable)
    if disable:
        await app.bots.stop_bot(bid)
    else:
        await app.bots.start_bot(bid)
    await app.audit("owner.bot_disable" if disable else "owner.bot_enable", "ok", user_id=cb.from_user.id, bot_id=bid)
    await bot_view(cb, app)


@router.callback_query(F.data.startswith("owner:users:"))
async def users(cb: CallbackQuery, app) -> None:
    page = max(iarg(cb, 2), 0)
    total = await app.repos.users.count()
    items = await app.repos.users.page(page * PER, PER)
    rows = [[b(f"{'🚫 ' if u['is_banned'] else ''}{u['first_name'][:16]} · {u['id']} · {u['bots']}🤖", f"owner:{'unban' if u['is_banned'] else 'uban'}:{u['id']}")] for u in items]
    pg = pager("owner:users", page, total, PER)
    if pg:
        rows.append(pg)
    await show(cb, "👥 <b>Users</b>\nTap a user to ban/unban.", kb(rows, "owner:home"))


@router.callback_query(F.data.startswith(("owner:uban:", "owner:unban:")))
async def ban_toggle(cb: CallbackQuery, app) -> None:
    uid = iarg(cb, 2)
    if app.is_platform_owner(uid):
        return await alert(cb, "You can't ban the owner.")
    ban = arg(cb, 1) == "uban"
    await app.repos.users.set_banned(uid, ban)
    if ban:
        for x in await app.repos.bots.list_owned(uid):
            await app.bots.stop_bot(x["id"])
    else:
        for x in await app.repos.bots.list_owned(uid):
            await app.bots.start_bot(x["id"])
    await app.audit("owner.ban" if ban else "owner.unban", "ok", user_id=cb.from_user.id, detail=str(uid))
    cb.data = "owner:users:0"
    await users(cb, app)


@router.callback_query(F.data == "owner:ban")
async def ban_prompt(cb: CallbackQuery, app) -> None:
    await app.wizard.set(cb.from_user.id, "owner_ban")
    await show(cb, "Send the user ID to ban. Prefix with <code>-</code> to unban (e.g. <code>-12345</code>).", kb([], "owner:home"))


@on_input("owner_ban")
async def in_ban(m: Message, app, data: dict) -> None:
    if not app.is_platform_owner(m.from_user.id):
        return
    raw = (m.text or "").strip()
    un = raw.startswith("-")
    if not raw.lstrip("-").isdigit() or app.is_platform_owner(int(raw.lstrip("-"))):
        return await m.answer("❌ Send a valid user ID.")
    uid = int(raw.lstrip("-"))
    await app.repos.users.set_banned(uid, not un)
    for x in await app.repos.bots.list_owned(uid):
        await (app.bots.start_bot(x["id"]) if un else app.bots.stop_bot(x["id"]))
    await app.wizard.clear(m.from_user.id)
    await m.answer(f"✅ User {uid} {'unbanned' if un else 'banned'}.", reply_markup=kb([], "owner:home"))


@router.callback_query(F.data == "owner:limit")
async def limit_prompt(cb: CallbackQuery, app) -> None:
    await app.wizard.set(cb.from_user.id, "owner_limit")
    await show(cb, f"Send <code>USER_ID LIMIT</code> (e.g. <code>12345 10</code>). Use <code>default</code> as limit to reset "
                   f"(default is {app.settings.max_bots_per_user}).", kb([], "owner:home"))


@on_input("owner_limit")
async def in_limit(m: Message, app, data: dict) -> None:
    if not app.is_platform_owner(m.from_user.id):
        return
    parts = (m.text or "").split()
    if len(parts) != 2 or not parts[0].isdigit() or not (parts[1].isdigit() or parts[1] == "default"):
        return await m.answer("❌ Format: USER_ID LIMIT")
    lim = None if parts[1] == "default" else min(int(parts[1]), 1000)
    if not await app.repos.users.get(int(parts[0])):
        return await m.answer("❌ Unknown user.")
    await app.repos.users.set_limit(int(parts[0]), lim)
    await app.wizard.clear(m.from_user.id)
    await m.answer("✅ Limit updated.", reply_markup=kb([], "owner:home"))


async def _logs(cb, app, errors: bool) -> None:
    rows = await app.repos.platform.recent_logs(15, errors_only=errors)
    txt = "\n".join(f"{r['ts']:%m-%d %H:%M} u={r['user_id'] or '-'} b={r['bot_id'] or '-'} {esc(r['action'])} {esc(r['status'])} {esc(r['error_code'] or '')}" for r in rows) or "Nothing yet."
    await show(cb, f"{'❗ <b>Errors</b>' if errors else '📜 <b>Logs</b>'}\n\n<pre>{txt}</pre>", kb([], "owner:home"))


@router.callback_query(F.data == "owner:logs")
async def logs(cb: CallbackQuery, app) -> None:
    await _logs(cb, app, False)


@router.callback_query(F.data == "owner:errs")
async def errs(cb: CallbackQuery, app) -> None:
    await _logs(cb, app, True)


@router.callback_query(F.data == "owner:feat")
async def feat(cb: CallbackQuery, app) -> None:
    f = await app.features()
    labels = {"scripts": "🐍 Python scripts", "custom_attribution": "🏷 Custom attribution text", "new_bots": "➕ New bots allowed"}
    rows = [[b(f"{labels[k]}: {'ON' if f[k] else 'OFF'}", f"owner:flip:{k}")] for k in labels]
    await show(cb, "🎛 <b>Features</b>\n\n⚠️ Scripts run user code in resource-limited subprocesses. Read the README security notes before enabling.", kb(rows, "owner:home"))


@router.callback_query(F.data.startswith("owner:flip:"))
async def flip(cb: CallbackQuery, app) -> None:
    k = arg(cb, 2)
    f = await app.features()
    if k in f:
        await app.set_feature(k, not f[k])
        await app.audit("owner.feature", "ok", user_id=cb.from_user.id, detail=f"{k}={not f[k]}")
    await feat(cb, app)


@router.callback_query(F.data == "owner:res")
async def res(cb: CallbackQuery, app) -> None:
    rss = "n/a"
    try:
        with open("/proc/self/status") as fh:
            rss = next(l.split()[1] for l in fh if l.startswith("VmRSS"))
            rss = f"{int(rss) / 1024:.0f} MB"
    except Exception:
        pass
    ru = resource.getrusage(resource.RUSAGE_SELF)
    pool = app.db.pool
    text = (f"📟 <b>Resources</b>\n\nMemory (RSS): {rss}\nCPU time: {ru.ru_utime + ru.ru_stime:.0f}s\n"
            f"Running bots: {len(app.bots.runtimes)}\nAsyncio tasks: {len(asyncio.all_tasks())}\n"
            f"DB pool: {pool.get_size()} conns ({pool.get_idle_size()} idle)\nBroadcasts running: {len(app.broadcasts.tasks)}\nPID: {os.getpid()}")
    await show(cb, text, kb([[b("🔄 Refresh", "owner:res")]], "owner:home"))


@router.callback_query(F.data == "owner:cast")
async def cast_prompt(cb: CallbackQuery, app) -> None:
    await app.wizard.set(cb.from_user.id, "owner_cast")
    await show(cb, "📣 Send the announcement text. It goes to every platform user via this bot (paced).", kb([], "owner:home"))


@on_input("owner_cast")
async def in_cast(m: Message, app, data: dict) -> None:
    if not app.is_platform_owner(m.from_user.id):
        return
    text = clean(m.text, 3500)
    if not text:
        return await m.answer("Send text.")
    await app.wizard.clear(m.from_user.id)
    ids = await app.repos.users.ids()
    await m.answer(f"📣 Sending to {len(ids):,} users…")

    async def run():
        sent = failed = 0
        for uid in ids:
            for _ in range(3):
                try:
                    await app.manager_bot.send_message(uid, f"📣 <b>Announcement</b>\n\n{esc(text)}")
                    sent += 1
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                except TelegramForbiddenError:
                    failed += 1
                    break
                except Exception:
                    failed += 1
                    break
            await asyncio.sleep(0.05)  # ~20 msg/s
        await app.audit("owner.announce", "ok", user_id=m.from_user.id, detail=f"sent={sent} failed={failed}")
        await app.manager_bot.send_message(m.from_user.id, f"📣 Announcement done: ✅ {sent} · ❌ {failed}")
    asyncio.create_task(run())
