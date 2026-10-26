from __future__ import annotations


class BroadcastRepo:
    def __init__(self, db):
        self.db = db

    async def create(self, bot_id, owner_id, ctype, text, media_id):
        return await self.db.fetchrow(
            """INSERT INTO broadcasts(bot_id,owner_id,content_type,text,media_id) VALUES($1,$2,$3,$4,$5) RETURNING *""",
            bot_id, owner_id, ctype, text, media_id)

    async def get(self, bot_id: int, bid: int):
        return await self.db.fetchrow("SELECT * FROM broadcasts WHERE id=$1 AND bot_id=$2", bid, bot_id)

    async def get_internal(self, bid: int):
        return await self.db.fetchrow("SELECT * FROM broadcasts WHERE id=$1", bid)

    async def list(self, bot_id: int, limit: int = 5):
        return await self.db.fetch("SELECT * FROM broadcasts WHERE bot_id=$1 ORDER BY id DESC LIMIT $2", bot_id, limit)

    async def eligible(self, bot_id: int) -> int:
        return await self.db.fetchval(
            "SELECT count(*) FROM bot_users WHERE bot_id=$1 AND NOT is_banned AND NOT is_blocked", bot_id)

    async def snapshot(self, bid: int, bot_id: int) -> int:
        """Freeze the recipient list at start time. Only draft broadcasts can be started."""
        async with self.db.transaction() as c:
            st = await c.fetchval("SELECT status FROM broadcasts WHERE id=$1 AND bot_id=$2 FOR UPDATE", bid, bot_id)
            if st != "draft":
                return -1
            await c.execute(
                """INSERT INTO broadcast_recipients(broadcast_id,user_id)
                   SELECT $1, user_id FROM bot_users WHERE bot_id=$2 AND NOT is_banned AND NOT is_blocked""", bid, bot_id)
            total = await c.fetchval("SELECT count(*) FROM broadcast_recipients WHERE broadcast_id=$1", bid)
            await c.execute("UPDATE broadcasts SET status='running', total=$2, started_at=now() WHERE id=$1", bid, total)
            return total

    async def set_status(self, bid: int, status: str, from_states: tuple[str, ...] | None = None) -> bool:
        finished = ", finished_at=now()" if status in ("done", "cancelled", "failed") else ""
        if from_states:
            r = await self.db.execute(
                f"UPDATE broadcasts SET status=$2{finished} WHERE id=$1 AND status = ANY($3::text[])",
                bid, status, list(from_states))
        else:
            r = await self.db.execute(f"UPDATE broadcasts SET status=$2{finished} WHERE id=$1", bid, status)
        return r.endswith("1")

    async def status(self, bid: int):
        return await self.db.fetchval("SELECT status FROM broadcasts WHERE id=$1", bid)

    async def next_pending(self, bid: int, limit: int):
        return await self.db.fetch(
            """SELECT r.user_id, u.first_name, u.last_name, u.username FROM broadcast_recipients r
               LEFT JOIN broadcasts b ON b.id=r.broadcast_id
               LEFT JOIN bot_users u ON u.bot_id=b.bot_id AND u.user_id=r.user_id
               WHERE r.broadcast_id=$1 AND r.status='pending' ORDER BY r.user_id LIMIT $2""", bid, limit)

    async def mark(self, bid: int, uid: int, status: str, error: str | None = None) -> None:
        await self.db.execute(
            "UPDATE broadcast_recipients SET status=$3, error=$4 WHERE broadcast_id=$1 AND user_id=$2",
            bid, uid, status, (error or None) and error[:200])

    async def progress(self, bid: int):
        return await self.db.fetchrow(
            """SELECT count(*) AS total, count(*) FILTER (WHERE status='sent') AS sent,
                      count(*) FILTER (WHERE status='failed') AS failed,
                      count(*) FILTER (WHERE status='blocked') AS blocked,
                      count(*) FILTER (WHERE status='pending') AS remaining
               FROM broadcast_recipients WHERE broadcast_id=$1""", bid)

    async def running_ids(self):
        return [r["id"] for r in await self.db.fetch("SELECT id FROM broadcasts WHERE status='running'")]

    async def delete_draft(self, bot_id: int, bid: int) -> None:
        await self.db.execute("DELETE FROM broadcasts WHERE id=$1 AND bot_id=$2 AND status='draft'", bid, bot_id)
        await self.db.execute("DELETE FROM buttons WHERE bot_id=$1 AND set_key=$2", bot_id, f"b{bid}")

    async def active_count(self, bot_id: int) -> int:
        return await self.db.fetchval("SELECT count(*) FROM broadcasts WHERE bot_id=$1 AND status IN ('running','paused')", bot_id)
