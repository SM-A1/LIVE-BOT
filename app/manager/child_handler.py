from __future__ import annotations

import logging

from aiogram.exceptions import TelegramForbiddenError

from app.manager import attribution
from app.manager.sender import build_script_markup, send_rich
from app.services.matching import matches
from app.services.variables import vars_for

log = logging.getLogger("app.child")


class ChildHandler:
    """Processes updates for managed bots. All lookups are scoped by the runtime's own bot id."""

    def __init__(self, app):
        self.app = app
        self.r = app.repos

    async def handle(self, rt, upd) -> None:
        try:
            if upd.message:
                await self._message(rt, upd.message)
            elif upd.callback_query:
                await self._callback(rt, upd.callback_query)
            elif upd.my_chat_member:
                mc = upd.my_chat_member
                if mc.chat.type == "private":
                    st = mc.new_chat_member.status
                    if st in ("kicked", "left"):
                        await self.r.botusers.mark_blocked(rt.id, mc.chat.id, True)
                    elif st == "member":
                        await self.r.botusers.mark_blocked(rt.id, mc.chat.id, False)
        except TelegramForbiddenError:
            pass  # user blocked the bot / bot removed from chat
        except Exception as exc:
            await self.app.audit("child.update", "error", bot_id=rt.id, error_code=type(exc).__name__, detail=str(exc))

    # --- messages ---------------------------------------------------------
    async def _prelude(self, rt, user, chat, count: bool):
        """Throttle, track the user, enforce bans. Returns (cache, is_admin) or None to ignore."""
        if user is None or user.is_bot:
            return None
        if not await self.app.throttle.hit(f"cu:{rt.id}:{user.id}", 10, 10):
            return None
        cache = await rt.get_cache(self.r)
        if chat.type != "private" and not cache.settings["group_mode"]:
            return None
        bu = await self.r.botusers.seen(rt.id, user, count)
        if bu["is_banned"]:
            return None
        admin = user.id == rt.owner_id or user.id in cache.admins
        if user.id == rt.owner_id and cache.settings["attribution_pending"]:
            await self._attribution(rt, cache)
        return cache, admin

    async def _attribution(self, rt, cache) -> None:
        s = cache.settings
        await self.r.bots.set_setting(rt.id, "attribution_pending", False)
        rt.invalidate()
        if s["attribution_enabled"]:
            await attribution.send_attribution(self.app, rt.bot, rt.owner_id, rt.id)

    async def _message(self, rt, m) -> None:
        pre = await self._prelude(rt, m.from_user, m.chat, True)
        if not pre:
            return
        cache, admin = pre
        if m.new_chat_members:
            w = cache.welcome
            if w["enabled"] and w["group_enabled"] and not w["private_only"]:
                for nm in m.new_chat_members:
                    if not nm.is_bot:
                        await self._welcome(rt, cache, nm, m.chat)
            return
        s = cache.settings
        if s["maintenance_mode"] and not admin:
            await send_rich(rt, self.r, m.chat.id, s["maintenance_text"] or "🛠 We're doing some maintenance. Please try again soon.",
                            vars_for(rt, m.from_user, m.chat.id))
            return
        text = (m.text or m.caption or "").strip()
        if text:
            await self._dispatch(rt, cache, text, m.from_user, m.chat, admin)

    async def _callback(self, rt, cq) -> None:
        data = cq.data or ""
        if not data.startswith("u:") or cq.message is None:
            await rt.bot.answer_callback_query(cq.id)
            return
        await rt.bot.answer_callback_query(cq.id)
        pre = await self._prelude(rt, cq.from_user, cq.message.chat, False)
        if pre:
            cache, admin = pre
            await self._dispatch(rt, cache, data[2:], cq.from_user, cq.message.chat, admin)

    async def _dispatch(self, rt, cache, text, user, chat, admin) -> None:
        if text.startswith("/"):
            head, _, args = text.partition(" ")
            name, _, mention = head[1:].partition("@")
            if mention and mention.lower() != rt.username.lower():
                return
            name = name.lower()
            cmd = cache.commands.get(name)
            sent = False
            if name == "start" and chat.type == "private":
                sent = await self._welcome(rt, cache, user, chat)
                if not cmd and not sent:
                    await send_rich(rt, self.r, chat.id, "👋 Hello {first_name}!", vars_for(rt, user, chat.id))
            if cmd:
                await self._run_command(rt, cache, cmd, user, chat, admin, text, args.strip())
            return
        for r in cache.responses:
            if matches(r["match_mode"], r["trigger"], text, r["case_insensitive"]):
                await send_rich(rt, self.r, chat.id, r["text"], vars_for(rt, user, chat.id),
                                rows=cache.buttons.get(f"r{r['id']}"))
                return

    async def _run_command(self, rt, cache, cmd, user, chat, admin, text, args) -> None:
        if cmd["scope"] == "private" and chat.type != "private":
            return
        if cmd["scope"] == "group" and chat.type == "private":
            return
        v = vars_for(rt, user, chat.id)
        if cmd["admin_only"] and not admin:
            await send_rich(rt, self.r, chat.id, "⛔ This command is for admins only.", v)
            return
        await self.r.botusers.log_command(rt.id, cmd["name"])
        if cmd["response_type"] == "script":
            await self._script(rt, cache, cmd, user, chat, admin, text, args)
            return
        media = await self.r.media.meta(rt.id, cmd["media_id"]) if cmd["media_id"] else None
        await send_rich(rt, self.r, chat.id, cmd["text"] or "…", v, media, cache.buttons.get(f"c{cmd['id']}"))

    async def _welcome(self, rt, cache, user, chat) -> bool:
        w = cache.welcome
        if not w["enabled"]:
            return False
        if chat.type != "private" and (w["private_only"] or not w["group_enabled"]):
            return False
        if w["delete_previous"]:
            prev = await self.r.welcome.last_sent(rt.id, chat.id)
            if prev:
                try:
                    await rt.bot.delete_message(chat.id, prev)
                except Exception:
                    pass
        media = await self.r.media.meta(rt.id, w["media_id"]) if w["media_id"] else None
        msg = await send_rich(rt, self.r, chat.id, w["text"], vars_for(rt, user, chat.id), media, cache.buttons.get("w"))
        await self.r.welcome.record(rt.id, chat.id, msg.message_id)
        return True

    async def _script(self, rt, cache, cmd, user, chat, admin, text, args) -> None:
        v = vars_for(rt, user, chat.id)
        if not (await self.app.features())["scripts"]:
            await send_rich(rt, self.r, chat.id, "⚠️ Python scripts are currently disabled by the platform.", v)
            return
        sc = await self.r.scripts.get(rt.id, cmd["script_id"]) if cmd["script_id"] else None
        if not sc or not sc["enabled"]:
            await send_rich(rt, self.r, chat.id, "⚠️ This command has no active script.", v)
            return
        ctx = {"text": text, "args": args, "is_admin": admin,
               "user": {"id": user.id, "first_name": user.first_name or "", "last_name": user.last_name or "",
                        "username": user.username or ""},
               "chat": {"id": chat.id, "type": chat.type}, "bot": {"username": rt.username, "name": rt.name}}
        res = await self.app.sandbox.run(sc["code"], ctx)
        await self.r.scripts.set_field(rt.id, sc["id"], "last_error", res.error)
        if res.error:
            await self.app.audit("script.run", "error", bot_id=rt.id, error_code="script_error", detail=res.error)
            note = f"⚠️ Script error: {res.error}" if (cache.settings["developer_mode"] and admin) \
                else "⚠️ Sorry, something went wrong while running this command."
            await send_rich(rt, self.r, chat.id, note.replace("{", "(").replace("}", ")"), v)
            return
        for a in res.actions:
            await rt.pacer.wait()
            markup = build_script_markup(a["rows"]) if a["op"] == "reply_buttons" else None
            await rt.bot.send_message(chat.id, a["text"], reply_markup=markup, disable_web_page_preview=True)
