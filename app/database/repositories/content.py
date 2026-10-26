from __future__ import annotations

CMD_FIELDS = {"description", "aliases", "response_type", "text", "media_id", "script_id", "scope", "admin_only", "enabled"}
RSP_FIELDS = {"trigger", "match_mode", "case_insensitive", "text", "enabled"}
WEL_FIELDS = {"enabled", "text", "media_id", "delete_previous", "private_only", "group_enabled"}
SCR_FIELDS = {"code", "enabled", "last_error", "name"}


class CommandRepo:
    def __init__(self, db):
        self.db = db

    async def list(self, bot_id: int):
        return await self.db.fetch("SELECT * FROM commands WHERE bot_id=$1 ORDER BY name", bot_id)

    async def get(self, bot_id: int, cid: int):
        return await self.db.fetchrow("SELECT * FROM commands WHERE id=$1 AND bot_id=$2", cid, bot_id)

    async def count(self, bot_id: int) -> int:
        return await self.db.fetchval("SELECT count(*) FROM commands WHERE bot_id=$1", bot_id)

    async def create(self, bot_id, name, response_type="text", text="", media_id=None, script_id=None):
        return await self.db.fetchrow(
            """INSERT INTO commands(bot_id,name,response_type,text,media_id,script_id)
               VALUES($1,$2,$3,$4,$5,$6) RETURNING *""", bot_id, name, response_type, text, media_id, script_id)

    async def set_field(self, bot_id: int, cid: int, field: str, value) -> None:
        if field not in CMD_FIELDS:
            raise ValueError("bad field")
        await self.db.execute(f"UPDATE commands SET {field}=$3 WHERE id=$1 AND bot_id=$2", cid, bot_id, value)

    async def delete(self, bot_id: int, cid: int) -> None:
        await self.db.execute("DELETE FROM commands WHERE id=$1 AND bot_id=$2", cid, bot_id)
        await self.db.execute("DELETE FROM buttons WHERE bot_id=$1 AND set_key=$2", bot_id, f"c{cid}")

    async def taken_names(self, bot_id: int, exclude_id: int | None = None) -> set[str]:
        rows = await self.db.fetch("SELECT id, name, aliases FROM commands WHERE bot_id=$1", bot_id)
        out: set[str] = set()
        for r in rows:
            if r["id"] != exclude_id:
                out.add(r["name"]); out.update(r["aliases"])
        return out


class ResponseRepo:
    def __init__(self, db):
        self.db = db

    async def list(self, bot_id: int):
        return await self.db.fetch("SELECT * FROM responses WHERE bot_id=$1 ORDER BY id", bot_id)

    async def get(self, bot_id: int, rid: int):
        return await self.db.fetchrow("SELECT * FROM responses WHERE id=$1 AND bot_id=$2", rid, bot_id)

    async def count(self, bot_id: int) -> int:
        return await self.db.fetchval("SELECT count(*) FROM responses WHERE bot_id=$1", bot_id)

    async def create(self, bot_id, trigger, mode, text, ci=True):
        return await self.db.fetchrow(
            """INSERT INTO responses(bot_id,trigger,match_mode,text,case_insensitive)
               VALUES($1,$2,$3,$4,$5) RETURNING *""", bot_id, trigger, mode, text, ci)

    async def set_field(self, bot_id: int, rid: int, field: str, value) -> None:
        if field not in RSP_FIELDS:
            raise ValueError("bad field")
        await self.db.execute(f"UPDATE responses SET {field}=$3 WHERE id=$1 AND bot_id=$2", rid, bot_id, value)

    async def delete(self, bot_id: int, rid: int) -> None:
        await self.db.execute("DELETE FROM responses WHERE id=$1 AND bot_id=$2", rid, bot_id)
        await self.db.execute("DELETE FROM buttons WHERE bot_id=$1 AND set_key=$2", bot_id, f"r{rid}")


class ButtonRepo:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def _group(rows):
        out: dict[str, list[list[dict]]] = {}
        last: dict[str, int] = {}
        for r in rows:
            k = r["set_key"]
            grid = out.setdefault(k, [])
            if last.get(k) != r["row_idx"]:
                grid.append([]); last[k] = r["row_idx"]
            grid[-1].append({"label": r["label"], "kind": r["kind"], "value": r["value"]})
        return out

    async def layout(self, bot_id: int, key: str):
        rows = await self.db.fetch(
            "SELECT * FROM buttons WHERE bot_id=$1 AND set_key=$2 ORDER BY row_idx, pos", bot_id, key)
        return self._group(rows).get(key, [])

    async def all_for_bot(self, bot_id: int):
        rows = await self.db.fetch("SELECT * FROM buttons WHERE bot_id=$1 ORDER BY set_key, row_idx, pos", bot_id)
        return self._group(rows)

    async def save_layout(self, bot_id: int, key: str, rows: list[list[dict]]) -> None:
        async with self.db.transaction() as c:
            await c.execute("DELETE FROM buttons WHERE bot_id=$1 AND set_key=$2", bot_id, key)
            for i, row in enumerate(rows):
                for j, b in enumerate(row):
                    await c.execute(
                        "INSERT INTO buttons(bot_id,set_key,row_idx,pos,label,kind,value) VALUES($1,$2,$3,$4,$5,$6,$7)",
                        bot_id, key, i, j, b["label"], b["kind"], b["value"])


class WelcomeRepo:
    def __init__(self, db):
        self.db = db

    async def get(self, bot_id: int):
        return await self.db.fetchrow("SELECT * FROM welcome_messages WHERE bot_id=$1", bot_id)

    async def set_field(self, bot_id: int, field: str, value) -> None:
        if field not in WEL_FIELDS:
            raise ValueError("bad field")
        await self.db.execute(f"UPDATE welcome_messages SET {field}=$2 WHERE bot_id=$1", bot_id, value)

    async def last_sent(self, bot_id: int, chat_id: int):
        return await self.db.fetchval("SELECT message_id FROM welcome_sent WHERE bot_id=$1 AND chat_id=$2", bot_id, chat_id)

    async def record(self, bot_id: int, chat_id: int, mid: int) -> None:
        await self.db.execute(
            """INSERT INTO welcome_sent(bot_id,chat_id,message_id) VALUES($1,$2,$3)
               ON CONFLICT (bot_id,chat_id) DO UPDATE SET message_id=EXCLUDED.message_id""", bot_id, chat_id, mid)


class MediaRepo:
    def __init__(self, db):
        self.db = db

    async def add(self, bot_id: int, kind: str, filename: str, data: bytes) -> int:
        return await self.db.fetchval(
            "INSERT INTO media(bot_id,kind,filename,data) VALUES($1,$2,$3,$4) RETURNING id", bot_id, kind, filename, data)

    async def meta(self, bot_id: int, mid: int):
        return await self.db.fetchrow("SELECT id, kind, filename, tg_file_id FROM media WHERE id=$1 AND bot_id=$2", mid, bot_id)

    async def data(self, bot_id: int, mid: int):
        return await self.db.fetchrow("SELECT data, filename FROM media WHERE id=$1 AND bot_id=$2", mid, bot_id)

    async def set_file_id(self, mid: int, fid: str) -> None:
        await self.db.execute("UPDATE media SET tg_file_id=$2 WHERE id=$1", mid, fid)

    async def delete(self, bot_id: int, mid: int | None) -> None:
        if mid:
            await self.db.execute("DELETE FROM media WHERE id=$1 AND bot_id=$2", mid, bot_id)

    async def count(self, bot_id: int) -> int:
        return await self.db.fetchval("SELECT count(*) FROM media WHERE bot_id=$1", bot_id)


class ScriptRepo:
    def __init__(self, db):
        self.db = db

    async def list(self, bot_id: int):
        return await self.db.fetch("SELECT * FROM script_projects WHERE bot_id=$1 ORDER BY name", bot_id)

    async def get(self, bot_id: int, sid: int):
        return await self.db.fetchrow("SELECT * FROM script_projects WHERE id=$1 AND bot_id=$2", sid, bot_id)

    async def count(self, bot_id: int) -> int:
        return await self.db.fetchval("SELECT count(*) FROM script_projects WHERE bot_id=$1", bot_id)

    async def create(self, bot_id: int, name: str, code: str):
        return await self.db.fetchrow(
            "INSERT INTO script_projects(bot_id,name,code) VALUES($1,$2,$3) RETURNING *", bot_id, name, code)

    async def set_field(self, bot_id: int, sid: int, field: str, value) -> None:
        if field not in SCR_FIELDS:
            raise ValueError("bad field")
        await self.db.execute(
            f"UPDATE script_projects SET {field}=$3, updated_at=now() WHERE id=$1 AND bot_id=$2", sid, bot_id, value)

    async def delete(self, bot_id: int, sid: int) -> None:
        await self.db.execute("DELETE FROM script_projects WHERE id=$1 AND bot_id=$2", sid, bot_id)
