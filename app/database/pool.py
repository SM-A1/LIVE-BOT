from __future__ import annotations

import json
from contextlib import asynccontextmanager

import asyncpg


class Database:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def connect(cls, dsn: str, min_size: int, max_size: int) -> "Database":
        async def init(conn: asyncpg.Connection) -> None:
            await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")

        pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size, init=init, command_timeout=30)
        return cls(pool)

    async def fetch(self, q: str, *a):
        return await self.pool.fetch(q, *a)

    async def fetchrow(self, q: str, *a):
        return await self.pool.fetchrow(q, *a)

    async def fetchval(self, q: str, *a):
        return await self.pool.fetchval(q, *a)

    async def execute(self, q: str, *a):
        return await self.pool.execute(q, *a)

    @asynccontextmanager
    async def transaction(self):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def close(self) -> None:
        await self.pool.close()
