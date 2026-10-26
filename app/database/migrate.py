from __future__ import annotations

from pathlib import Path

from app.database.pool import Database
from app.security.logs import log_event

MIGRATIONS = Path(__file__).parent / "migrations"
LOCK_ID = 727274


async def run_migrations(db: Database) -> None:
    async with db.pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_lock($1)", LOCK_ID)
        try:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations("
                "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            applied = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
            for f in sorted(MIGRATIONS.glob("*.sql")):
                if f.stem in applied:
                    continue
                async with conn.transaction():
                    await conn.execute(f.read_text(encoding="utf-8"))
                    await conn.execute("INSERT INTO schema_migrations(version) VALUES($1)", f.stem)
                log_event("migration", "ok", msg=f"applied {f.stem}")
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", LOCK_ID)
