from __future__ import annotations

import html
import re

_VAR = re.compile(r"\{(first_name|last_name|username|user_id|chat_id|bot_username|bot_name)\}")

VARIABLES_HELP = "{first_name} {last_name} {username} {user_id} {chat_id} {bot_username} {bot_name}"


def vars_for(rt, user, chat_id: int) -> dict[str, str]:
    return {
        "first_name": getattr(user, "first_name", "") or "",
        "last_name": getattr(user, "last_name", "") or "",
        "username": getattr(user, "username", "") or "",
        "user_id": str(getattr(user, "id", "")),
        "chat_id": str(chat_id),
        "bot_username": rt.username or "",
        "bot_name": rt.name or "",
    }


def render(text: str, values: dict[str, str], html_mode: bool = True) -> str:
    esc = html.escape if html_mode else (lambda s: s)
    return _VAR.sub(lambda m: esc(values.get(m.group(1), "")), text)
