from __future__ import annotations

import re

import regex

TOKEN_RE = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{30,50}$")
COMMAND_RE = re.compile(r"^[a-z0-9_]{1,32}$")
CALLBACK_RE = re.compile(r"^[a-z]{1,6}:[a-z_]{1,12}(:[\w.\-]{1,24}){0,4}$")


def clean(text: str | None, maxlen: int) -> str:
    return (text or "").replace("\x00", "").strip()[:maxlen]


def valid_regex(pattern: str) -> bool:
    """Compile check plus a cheap catastrophic-backtracking probe (matching also runs with a timeout)."""
    if not pattern or len(pattern) > 200:
        return False
    if re.search(r"[+*}]\)?[+*{]", pattern) or re.search(r"\([^)]*[+*][^)]*\)[+*{]", pattern):
        return False  # nested quantifiers => catastrophic backtracking risk
    try:
        regex.compile(pattern)
        regex.search(pattern, "a" * 200 + "!", timeout=0.05)
        return True
    except (regex.error, TimeoutError):
        return False


def valid_url(url: str) -> bool:
    return bool(re.match(r"^(https://\S{3,500}|tg://\S{3,200})$", url))


def parse_names(raw: str) -> list[str] | None:
    """Parse 'a, /b c' into unique valid command names; None if any is invalid."""
    names: list[str] = []
    for part in re.split(r"[,\s]+", raw.strip()):
        part = part.lstrip("/").lower()
        if not part:
            continue
        if not COMMAND_RE.match(part):
            return None
        if part not in names:
            names.append(part)
    return names
