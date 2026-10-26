from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.common import b, kb
from app.bot.states.wizard import on_input
from app.bot.ui import alert, arg, esc, own, show
from app.security.validators import COMMAND_RE, clean, valid_url

router = Router(name="buttons")
MAX_BUTTONS, MAX_PER_ROW = 20, 3
KINDS = {"url": ("🔗 URL", "url"), "cb": ("🔁 Callback", "callback"), "cmd": ("⚡ Command", "command"),
         "web": ("🌐 Web App", "web_app"), "inl": ("🔎 Switch inline", "switch_inline")}


async def key_back(app, bot, key: str):
    """Validates that the button set belongs to this bot and returns the screen to go back to."""
    i = bot["id"]
    if key == "w":
        return f"wel:open:{i}"
    if key[:1] in "crb" and key[1:].isdigit():
        n = int(key[1:])
        if key[0] == "c" and await app.repos.commands.get(i, n):
            return f"cmd:view:{i}:{n}"
        if key[0] == "r" and await app.repos.responses.get(i, n):
            return f"rsp:view:{i}:{n}"
        if key[0] == "b":
            bc = await app.repos.broadcasts.get(i, n)
            if bc and bc["status"] == "draft":
                return f"bc:view:{i}:{n}"
    return None


@router.callback_query(F.data.startswith("btn:menu:"))
async def btn_menu(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    if not bot:
        return
    i = bot["id"]
    rows = [[b("👋 Welcome message", f"btn:open:{i}:w")],
            [b("📚 Command buttons", f"btn:pick:{i}:c"), b("📝 Response buttons", f"btn:pick:{i}:r")]]
    await show(cb, "🔘 <b>Button Builder</b>\n\nChoose where to add inline buttons.\n(Broadcast buttons: open a draft in 📢 Broadcast.)", kb(rows, f"bot:open:{i}"))


@router.callback_query(F.data.startswith("btn:pick:"))
async def btn_pick(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    which = arg(cb, 3)
    if not bot or which not in ("c", "r"):
        return
    if which == "c":
        rows = [[b(f"/{c['name']}", f"btn:open:{bot['id']}:c{c['id']}")] for c in (await app.repos.commands.list(bot["id"]))[:30]]
    else:
        rows = [[b(r["trigger"][:30], f"btn:open:{bot['id']}:r{r['id']}")] for r in (await app.repos.responses.list(bot["id"]))[:30]]
    await show(cb, "Pick one:" if rows else "Nothing to choose from yet.", kb(rows, f"btn:menu:{bot['id']}"))


async def render_builder(ev, app, bot, key: str) -> None:
    back = await key_back(app, bot, key)
    if back is None:
        return await alert(ev, "⚠️ Not found.")
    i = bot["id"]
    grid = await app.repos.buttons.layout(i, key)
    preview = "\n".join(" ".join(f"[{esc(x['label'])}]" for x in row) for row in grid) or "<i>No buttons yet.</i>"
    rows = [[b(x["label"], f"btn:item:{i}:{key}:{r}_{c}") for c, x in enumerate(row)] for r, row in enumerate(grid)]
    rows.append([b("➕ New row", f"btn:add:{i}:{key}:n"), b("➕ Same row", f"btn:add:{i}:{key}:s")])
    await show(ev, f"🔘 <b>Button Builder</b>\n\n{preview}\n\nTap a button to move or delete it.", kb(rows, back))


@router.callback_query(F.data.startswith("btn:open:"))
async def btn_open(cb: CallbackQuery, app) -> None:
    await app.wizard.clear(cb.from_user.id)
    bot = await own(cb, app, arg(cb, 2))
    if bot:
        await render_builder(cb, app, bot, arg(cb, 3))


def _pos(cb, i):
    try:
        r, c = arg(cb, i).split("_")
        return int(r), int(c)
    except ValueError:
        return None


@router.callback_query(F.data.startswith("btn:item:"))
async def btn_item(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    key, pos = arg(cb, 3), _pos(cb, 4)
    if not bot or not pos or await key_back(app, bot, key) is None:
        return
    grid = await app.repos.buttons.layout(bot["id"], key)
    try:
        x = grid[pos[0]][pos[1]]
    except IndexError:
        return await render_builder(cb, app, bot, key)
    i, p = bot["id"], arg(cb, 4)
    rows = [[b("⬅️", f"btn:mv:{i}:{key}:{p}:l"), b("⬆️", f"btn:mv:{i}:{key}:{p}:u"),
             b("⬇️", f"btn:mv:{i}:{key}:{p}:d"), b("➡️", f"btn:mv:{i}:{key}:{p}:r")],
            [b("🗑 Delete", f"btn:rm:{i}:{key}:{p}")]]
    await show(cb, f"🔘 <b>{esc(x['label'])}</b>\nType: {x['kind']}\nValue: <code>{esc(x['value']) or '—'}</code>", kb(rows, f"btn:open:{i}:{key}"))


@router.callback_query(F.data.startswith("btn:mv:") | F.data.startswith("btn:rm:"))
async def btn_move(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    key, pos = arg(cb, 3), _pos(cb, 4)
    if not bot or not pos or await key_back(app, bot, key) is None:
        return
    grid = await app.repos.buttons.layout(bot["id"], key)
    r, c = pos
    if r >= len(grid) or c >= len(grid[r]):
        return await render_builder(cb, app, bot, key)
    item = grid[r].pop(c)
    if arg(cb, 1) == "mv":
        d = arg(cb, 5)
        if d == "l":
            grid[r].insert(max(c - 1, 0), item)
        elif d == "r":
            grid[r].insert(min(c + 1, len(grid[r])), item)
        elif d == "u":
            (grid[r - 1].append(item) if r > 0 and len(grid[r - 1]) < MAX_PER_ROW else grid.insert(max(r, 0), [item]))
        elif d == "d":
            (grid[r + 1].insert(0, item) if r + 1 < len(grid) and len(grid[r + 1]) < MAX_PER_ROW else grid.insert(r + 1, [item]))
    grid = [row for row in grid if row]
    await app.repos.buttons.save_layout(bot["id"], key, grid)
    app.bots.invalidate(bot["id"])
    await render_builder(cb, app, bot, key)


@router.callback_query(F.data.startswith("btn:add:"))
async def btn_add(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    key, p = arg(cb, 3), arg(cb, 4)
    if not bot or p not in ("n", "s") or await key_back(app, bot, key) is None:
        return
    grid = await app.repos.buttons.layout(bot["id"], key)
    if sum(len(r) for r in grid) >= MAX_BUTTONS:
        return await alert(cb, f"⚠️ Max {MAX_BUTTONS} buttons per message.")
    rows = [[b(label, f"btn:kind:{bot['id']}:{key}:{p}:{k}")] for k, (label, _) in KINDS.items()]
    await show(cb, "➕ <b>Add button</b>\n\nChoose the button type:", kb(rows, f"btn:open:{bot['id']}:{key}"))


@router.callback_query(F.data.startswith("btn:kind:"))
async def btn_kind(cb: CallbackQuery, app) -> None:
    bot = await own(cb, app, arg(cb, 2))
    key, p, k = arg(cb, 3), arg(cb, 4), arg(cb, 5)
    if not bot or k not in KINDS or p not in ("n", "s") or await key_back(app, bot, key) is None:
        return
    await app.wizard.set(cb.from_user.id, "btn_label", bid=bot["id"], key=key, p=p, k=k)
    await show(cb, "✏️ Send the button <b>label</b> (e.g. <code>📢 Join Channel</code>, max 40 chars).", kb([], f"btn:open:{bot['id']}:{key}"))


@on_input("btn_label")
async def in_label(m: Message, app, data: dict) -> None:
    label = clean(m.text, 40)
    if not label:
        return await m.answer("Please send the label as text.")
    hints = {"url": "Send the <b>https://</b> link.", "cb": "Send the text the bot should process when pressed (max 55 chars). "
             "It behaves like the user typing it, so it can trigger a response.", "cmd": "Send the command name this button runs, e.g. <code>help</code>.",
             "web": "Send the <b>https://</b> URL of your Web App.", "inl": "Send the inline query text to insert (or <code>-</code> for empty)."}
    await app.wizard.set(m.from_user.id, "btn_value", **{**data, "label": label})
    await m.answer(hints[data["k"]])


@on_input("btn_value")
async def in_value(m: Message, app, data: dict) -> None:
    bot = await own(m, app, data["bid"])
    back = await key_back(app, bot, data["key"]) if bot else None
    if not bot or back is None:
        return
    raw, k = clean(m.text, 500), data["k"]
    if k in ("url", "web"):
        if not valid_url(raw) or (k == "web" and not raw.startswith("https://")):
            return await m.answer("❌ Please send a valid https:// link.")
        value = raw
    elif k == "cmd":
        name = raw.lstrip("/").lower()
        if not COMMAND_RE.match(name):
            return await m.answer("❌ Invalid command name.")
        value = "/" + name
    elif k == "cb":
        if not raw or len(raw.encode()) > 55:
            return await m.answer("❌ Send 1–55 characters.")
        value = raw
    else:
        value = "" if raw == "-" else raw[:100]
    grid = await app.repos.buttons.layout(bot["id"], data["key"])
    if sum(len(r) for r in grid) >= MAX_BUTTONS:
        return await m.answer("⚠️ Button limit reached.")
    new = {"label": data["label"], "kind": KINDS[k][1], "value": value}
    if data["p"] == "s" and grid and len(grid[-1]) < MAX_PER_ROW:
        grid[-1].append(new)
    else:
        grid.append([new])
    await app.repos.buttons.save_layout(bot["id"], data["key"], grid)
    await app.wizard.clear(m.from_user.id)
    app.bots.invalidate(bot["id"])
    await render_builder(m, app, bot, data["key"])
