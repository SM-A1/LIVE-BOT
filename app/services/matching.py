from __future__ import annotations

import regex


def matches(mode: str, trigger: str, text: str, ci: bool = True) -> bool:
    if mode == "regex":
        try:
            return regex.search(trigger, text, flags=regex.I if ci else 0, timeout=0.05) is not None
        except (TimeoutError, regex.error):
            return False
    a, b = text.strip(), trigger.strip()
    if ci:
        a, b = a.casefold(), b.casefold()
    return {"exact": a == b, "contains": b in a, "startswith": a.startswith(b), "endswith": a.endswith(b)}.get(mode, False)
