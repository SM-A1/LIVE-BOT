from __future__ import annotations

from app.security.logs import log_event

DEFAULT = "This bot was made using @{MANAGER_BOT_USERNAME}"


def build_text(identity, settings_row, allow_custom: bool) -> str | None:
    """Attribution text built from the *detected* manager username. None => skip gracefully."""
    if identity is None or not identity.username:
        return None
    template = DEFAULT
    custom = settings_row["attribution_text"] if settings_row else None
    if allow_custom and custom:
        template = custom
    return template.replace("{MANAGER_BOT_USERNAME}", identity.username)


async def send_attribution(app, bot, chat_id: int, bot_id: int) -> bool:
    """Best-effort. Never raises: attribution must not affect bot connection."""
    try:
        s = await app.repos.bots.settings(bot_id)
        if not s or not s["attribution_enabled"]:
            return True  # nothing to send
        text = build_text(await app.identity.get(), s, (await app.features())["custom_attribution"])
        if text is None:
            log_event("attribution", "skipped", bot_id=bot_id, msg="manager username unavailable")
            return False
        await bot.send_message(chat_id, text)
        log_event("attribution", "ok", bot_id=bot_id)
        return True
    except Exception as exc:  # Forbidden (owner never started the bot), network, etc.
        log_event("attribution", "error", bot_id=bot_id, error_code=type(exc).__name__)
        return False
