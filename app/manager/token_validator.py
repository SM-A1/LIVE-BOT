from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramUnauthorizedError

from app.security.validators import TOKEN_RE


class TokenCheckUnavailable(Exception):
    """Telegram could not be reached; the token is neither confirmed valid nor invalid."""


@dataclass(frozen=True)
class ValidatedBot:
    id: int
    username: str
    first_name: str


async def validate_token(token: str, session, manager_bot_id: int | None = None) -> ValidatedBot | None:
    """Returns bot info if valid, None if invalid. Raises TokenCheckUnavailable on network trouble."""
    if not TOKEN_RE.match(token):
        return None
    bot = Bot(token, session=session)
    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        return None
    except (TelegramNetworkError, TelegramRetryAfter) as exc:
        raise TokenCheckUnavailable from exc
    if not me.is_bot or not me.username or me.id == manager_bot_id:
        return None
    return ValidatedBot(me.id, me.username, me.first_name)
