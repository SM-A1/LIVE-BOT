from __future__ import annotations

from aiogram import Bot


async def child_bot(app, row) -> Bot:
    """The running bot instance if available, otherwise a short-lived one built from the encrypted token."""
    rt = app.bots.runtimes.get(row["id"])
    if rt:
        return rt.bot
    return Bot(app.vault.decrypt(row["token_enc"]), session=app.session)
