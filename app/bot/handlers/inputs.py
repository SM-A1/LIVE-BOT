from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from app.bot.states.wizard import INPUTS
from app.security.validators import TOKEN_RE

router = Router(name="inputs")


@router.message()
async def on_any(m: Message, app) -> None:
    """Routes free-form input to the active wizard step."""
    from app.bot.handlers.start import show_home
    uid = m.from_user.id
    sess = await app.wizard.get(uid)
    if sess and sess[0] in INPUTS:
        return await INPUTS[sess[0]](m, app, sess[1])
    if m.text and TOKEN_RE.match(m.text.strip()):  # convenience: a pasted token starts the add flow
        if not (await app.features())["new_bots"] and not app.is_platform_owner(uid):
            return await m.answer("🚧 Adding new bots is temporarily disabled.")
        if await app.repos.bots.count_owned(uid) >= await app.limit_for(uid):
            return await m.answer("⚠️ You reached your bot limit.")
        return await INPUTS["add_token"](m, app, {})
    await show_home(m, app)
