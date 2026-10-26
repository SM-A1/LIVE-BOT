from __future__ import annotations

import json

SETTING_FIELDS = {
    "maintenance_mode", "maintenance_text", "group_mode", "attribution_enabled", "attribution_text",
    "attribution_pending", "logging_enabled", "developer_mode", "update_mode",
}


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class UserRepo:
    def __init__(self, db):
        self.db = db

    async def upsert(self, u):
        return await self.db.fetchrow(
            """INSERT INTO users(id, username, first_name, last_name) VALUES($1,$2,$3,$4)
               ON CONFLICT (id) DO UPDATE SET username=EXCLUDED.username, first_name=EXCLUDED.first_name,
                 last_name=EXCLUDED.last_name, last_seen=now()
               RETURNING *""", u.id, u.username, u.first_name or "", u.last_name)

    async def get(self, uid: int):
        return await self.db.fetchrow("SELECT * FROM users WHERE id=$1", uid)

    async def set_banned(self, uid: int, v: bool) -> None:
        await self.db.execute("UPDATE users SET is_banned=$2 WHERE id=$1", uid, v)

    async def set_limit(self, uid: int, n: int | None) -> None:
        await self.db.execute("UPDATE users SET bot_limit=$2 WHERE id=$1", uid, n)

    async def count(self) -> int:
        return await self.db.fetchval("SELECT count(*) FROM users")

    async def page(self, offset: int, limit: int):
        return await self.db.fetch(
            """SELECT u.*, (SELECT count(*) FROM bots b WHERE b.owner_id=u.id) AS bots
               FROM users u ORDER BY last_seen DESC OFFSET $1 LIMIT $2""", offset, limit)

    async def ids(self):
        return [r["id"] for r in await self.db.fetch("SELECT id FROM users WHERE NOT is_banned")]


class BotRepo:
    SUMMARY = """SELECT b.*,
        (SELECT count(*) FROM bot_users u WHERE u.bot_id=b.id) AS users,
        (SELECT count(*) FROM commands c WHERE c.bot_id=b.id) AS commands,
        (SELECT count(*) FROM responses r WHERE r.bot_id=b.id) AS responses
        FROM bots b"""

    def __init__(self, db):
        self.db = db

    async def create(self, owner_id, tg_bot_id, username, first_name, token_enc):
        async with self.db.transaction() as c:
            row = await c.fetchrow(
                """INSERT INTO bots(owner_id, tg_bot_id, username, first_name, token_enc, status)
                   VALUES($1,$2,$3,$4,$5,'starting') RETURNING *""",
                owner_id, tg_bot_id, username, first_name, token_enc)
            await c.execute("INSERT INTO settings(bot_id) VALUES($1)", row["id"])
            await c.execute("INSERT INTO welcome_messages(bot_id) VALUES($1)", row["id"])
        return row

    async def find_by_tg(self, tg_bot_id: int):
        return await self.db.fetchrow("SELECT id, owner_id FROM bots WHERE tg_bot_id=$1", tg_bot_id)

    async def update_token(self, bot_id, owner_id, token_enc, username, first_name):
        await self.db.execute(
            "UPDATE bots SET token_enc=$3, username=$4, first_name=$5, last_error=NULL WHERE id=$1 AND owner_id=$2",
            bot_id, owner_id, token_enc, username, first_name)

    async def get_any(self, bot_id: int):
        return await self.db.fetchrow("SELECT * FROM bots WHERE id=$1", bot_id)

    async def get_owned(self, bot_id: int, owner_id: int):
        """The single ownership choke-point used by every manager-side action."""
        return await self.db.fetchrow("SELECT * FROM bots WHERE id=$1 AND owner_id=$2", bot_id, owner_id)

    async def dashboard(self, bot_id: int, owner_id: int):
        return await self.db.fetchrow(self.SUMMARY + " WHERE b.id=$1 AND b.owner_id=$2", bot_id, owner_id)

    async def list_owned(self, owner_id: int):
        return await self.db.fetch(self.SUMMARY + " WHERE b.owner_id=$1 ORDER BY b.id", owner_id)

    async def count_owned(self, owner_id: int) -> int:
        return await self.db.fetchval("SELECT count(*) FROM bots WHERE owner_id=$1", owner_id)

    async def delete_owned(self, bot_id: int, owner_id: int) -> bool:
        r = await self.db.execute("DELETE FROM bots WHERE id=$1 AND owner_id=$2", bot_id, owner_id)
        return r.endswith("1")

    async def set_status(self, bot_id: int, status: str, error: str | None = None) -> None:
        await self.db.execute("UPDATE bots SET status=$2, last_error=$3 WHERE id=$1", bot_id, status,
                              (error or None) and error[:300])

    async def set_name(self, bot_id: int, name: str) -> None:
        await self.db.execute("UPDATE bots SET first_name=$2 WHERE id=$1", bot_id, name)

    async def set_disabled(self, bot_id: int, v: bool) -> None:
        await self.db.execute("UPDATE bots SET is_disabled=$2 WHERE id=$1", bot_id, v)

    async def list_runnable(self):
        return await self.db.fetch("SELECT id FROM bots WHERE NOT is_disabled ORDER BY id")

    async def settings(self, bot_id: int):
        return await self.db.fetchrow("SELECT * FROM settings WHERE bot_id=$1", bot_id)

    async def set_setting(self, bot_id: int, field: str, value) -> None:
        if field not in SETTING_FIELDS:
            raise ValueError("unknown setting")
        await self.db.execute(f"UPDATE settings SET {field}=$2 WHERE bot_id=$1", bot_id, value)  # field whitelisted

    async def admins(self, bot_id: int) -> list[int]:
        return [r["user_id"] for r in await self.db.fetch("SELECT user_id FROM bot_admins WHERE bot_id=$1", bot_id)]

    async def add_admin(self, bot_id: int, uid: int) -> None:
        await self.db.execute("INSERT INTO bot_admins(bot_id,user_id) VALUES($1,$2) ON CONFLICT DO NOTHING", bot_id, uid)

    async def remove_admin(self, bot_id: int, uid: int) -> None:
        await self.db.execute("DELETE FROM bot_admins WHERE bot_id=$1 AND user_id=$2", bot_id, uid)

    async def totals(self):
        return await self.db.fetchrow(
            """SELECT (SELECT count(*) FROM users) AS users, (SELECT count(*) FROM bots) AS bots,
                      (SELECT count(*) FROM bots WHERE status='online') AS online,
                      (SELECT count(*) FROM bots WHERE status='error') AS errors,
                      (SELECT count(*) FROM bot_users) AS end_users""")

    async def totals_owner(self, owner_id: int):
        return await self.db.fetchrow(
            """SELECT count(*) AS bots, count(*) FILTER (WHERE status='online') AS online,
                      coalesce(sum((SELECT count(*) FROM bot_users u WHERE u.bot_id=b.id)),0) AS users
               FROM bots b WHERE owner_id=$1""", owner_id)

    async def page_all(self, offset: int, limit: int):
        return await self.db.fetch("SELECT * FROM bots ORDER BY id DESC OFFSET $1 LIMIT $2", offset, limit)


class BotUserRepo:
    def __init__(self, db):
        self.db = db

    async def seen(self, bot_id: int, u, count: bool = True):
        inc = 1 if count else 0
        row = await self.db.fetchrow(
            """INSERT INTO bot_users(bot_id,user_id,username,first_name,last_name,message_count)
               VALUES($1,$2,$3,$4,$5,$6)
               ON CONFLICT (bot_id,user_id) DO UPDATE SET username=EXCLUDED.username,
                 first_name=EXCLUDED.first_name, last_name=EXCLUDED.last_name, last_active=now(),
                 message_count=bot_users.message_count+$6, is_blocked=FALSE
               RETURNING is_banned, (xmax = 0) AS is_new""",
            bot_id, u.id, u.username, u.first_name or "", u.last_name, inc)
        if count:
            await self.db.execute(
                """INSERT INTO bot_daily(bot_id, day, messages, new_users) VALUES($1, current_date, 1, $2)
                   ON CONFLICT (bot_id, day) DO UPDATE SET messages=bot_daily.messages+1,
                     new_users=bot_daily.new_users+EXCLUDED.new_users""", bot_id, 1 if row["is_new"] else 0)
        return row

    async def mark_blocked(self, bot_id: int, uid: int, v: bool) -> None:
        await self.db.execute("UPDATE bot_users SET is_blocked=$3 WHERE bot_id=$1 AND user_id=$2", bot_id, uid, v)

    async def get(self, bot_id: int, uid: int):
        return await self.db.fetchrow("SELECT * FROM bot_users WHERE bot_id=$1 AND user_id=$2", bot_id, uid)

    def _where(self, q):
        if not q:
            return "", []
        if q.lstrip("@").isdigit():
            return " AND user_id=$2", [int(q.lstrip("@"))]
        return " AND (username ILIKE $2 OR first_name ILIKE $2 OR last_name ILIKE $2)", [_like(q.lstrip("@"))]

    async def page(self, bot_id: int, offset: int, limit: int, q: str | None = None):
        w, p = self._where(q)
        n = len(p) + 2
        return await self.db.fetch(
            f"SELECT * FROM bot_users WHERE bot_id=$1{w} ORDER BY last_active DESC OFFSET ${n} LIMIT ${n + 1}",
            bot_id, *p, offset, limit)

    async def count(self, bot_id: int, q: str | None = None) -> int:
        w, p = self._where(q)
        return await self.db.fetchval(f"SELECT count(*) FROM bot_users WHERE bot_id=$1{w}", bot_id, *p)

    async def set_banned(self, bot_id: int, uid: int, v: bool) -> None:
        await self.db.execute("UPDATE bot_users SET is_banned=$3 WHERE bot_id=$1 AND user_id=$2", bot_id, uid, v)

    async def stats(self, bot_id: int):
        return await self.db.fetchrow(
            """SELECT count(*) AS total,
                 count(*) FILTER (WHERE first_seen >= current_date) AS today,
                 count(*) FILTER (WHERE first_seen >= now() - interval '7 days') AS week,
                 count(*) FILTER (WHERE last_active >= now() - interval '24 hours') AS active,
                 count(*) FILTER (WHERE is_banned) AS banned,
                 count(*) FILTER (WHERE is_blocked) AS blocked
               FROM bot_users WHERE bot_id=$1""", bot_id)

    async def messages(self, bot_id: int):
        return await self.db.fetchrow(
            """SELECT coalesce(sum(messages),0) AS total,
                      coalesce(sum(messages) FILTER (WHERE day >= current_date - 6),0) AS week
               FROM bot_daily WHERE bot_id=$1""", bot_id)

    async def top_commands(self, bot_id: int, limit: int = 5):
        return await self.db.fetch(
            """SELECT name, sum(count)::int AS uses FROM command_usage
               WHERE bot_id=$1 AND used_on >= current_date - 29 GROUP BY name ORDER BY uses DESC LIMIT $2""",
            bot_id, limit)

    async def log_command(self, bot_id: int, name: str) -> None:
        await self.db.execute(
            """INSERT INTO command_usage(bot_id,name,used_on,count) VALUES($1,$2,current_date,1)
               ON CONFLICT (bot_id,name,used_on) DO UPDATE SET count=command_usage.count+1""", bot_id, name)

    async def broadcast_stats(self, bot_id: int):
        return await self.db.fetchrow(
            """SELECT count(*) AS total, coalesce(sum((SELECT count(*) FROM broadcast_recipients r
                      WHERE r.broadcast_id=b.id AND r.status='sent')),0)::int AS sent
               FROM broadcasts b WHERE b.bot_id=$1 AND b.status<>'draft'""", bot_id)


class PlatformRepo:
    def __init__(self, db):
        self.db = db

    async def get(self, key: str, default=None):
        row = await self.db.fetchrow("SELECT value FROM platform_settings WHERE key=$1", key)
        return row["value"] if row else default

    async def set(self, key: str, value) -> None:
        await self.db.execute(
            "INSERT INTO platform_settings(key,value) VALUES($1,$2) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
            key, value)

    async def log(self, action, status, user_id=None, bot_id=None, error_code=None, detail=None) -> None:
        await self.db.execute(
            "INSERT INTO logs(user_id,bot_id,action,status,error_code,detail) VALUES($1,$2,$3,$4,$5,$6)",
            user_id, bot_id, action, status, error_code, detail)

    async def recent_logs(self, limit=15, bot_id=None, errors_only=False):
        cond, args = [], []
        if bot_id is not None:
            args.append(bot_id); cond.append(f"bot_id=${len(args)}")
        if errors_only:
            cond.append("status<>'ok'")
        w = ("WHERE " + " AND ".join(cond)) if cond else ""
        args.append(limit)
        return await self.db.fetch(f"SELECT * FROM logs {w} ORDER BY id DESC LIMIT ${len(args)}", *args)

    async def prune_logs(self, days=30) -> None:
        await self.db.execute("DELETE FROM logs WHERE ts < now() - make_interval(days => $1)", days)

    async def session_get(self, uid: int):
        return await self.db.fetchrow(
            "SELECT state, data FROM sessions WHERE user_id=$1 AND updated_at > now() - interval '30 minutes'", uid)

    async def session_set(self, uid: int, state: str, data: dict) -> None:
        await self.db.execute(
            """INSERT INTO sessions(user_id,state,data,updated_at) VALUES($1,$2,$3,now())
               ON CONFLICT (user_id) DO UPDATE SET state=EXCLUDED.state, data=EXCLUDED.data, updated_at=now()""",
            uid, state, data)

    async def session_clear(self, uid: int) -> None:
        await self.db.execute("DELETE FROM sessions WHERE user_id=$1", uid)
