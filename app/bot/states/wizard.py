from __future__ import annotations

INPUTS: dict = {}


def on_input(state: str):
    """Register a handler for free-text/media input expected in wizard state `state`."""
    def deco(fn):
        INPUTS[state] = fn
        return fn
    return deco


class Wizard:
    """DB-backed conversation state (survives restarts, expires after 30 minutes)."""

    def __init__(self, repo):
        self.repo = repo

    async def set(self, uid: int, state: str, **data) -> None:
        await self.repo.session_set(uid, state, data)

    async def get(self, uid: int):
        row = await self.repo.session_get(uid)
        return (row["state"], dict(row["data"])) if row else None

    async def clear(self, uid: int) -> None:
        await self.repo.session_clear(uid)
