from __future__ import annotations

import html


async def render_dashboard(repos, bot) -> str:
    st = await repos.botusers.stats(bot["id"])
    msgs = await repos.botusers.messages(bot["id"])
    top = await repos.botusers.top_commands(bot["id"])
    bc = await repos.botusers.broadcast_stats(bot["id"])
    top_txt = "\n".join(f"  {i}. /{html.escape(r['name'])} — {r['uses']:,}" for i, r in enumerate(top, 1)) or "  No data yet"
    return (
        f"📊 <b>Analytics — @{html.escape(bot['username'])}</b>\n\n"
        f"👥 Total users: <b>{st['total']:,}</b>\n"
        f"🆕 New today: <b>{st['today']:,}</b>  ·  This week: <b>{st['week']:,}</b>\n"
        f"🔥 Active (24h): <b>{st['active']:,}</b>\n"
        f"🚫 Banned: {st['banned']:,}  ·  ⛔ Blocked the bot: {st['blocked']:,}\n\n"
        f"💬 Messages: <b>{msgs['total']:,}</b> (7 days: {msgs['week']:,})\n\n"
        f"⚡ <b>Top commands (30 days)</b>\n{top_txt}\n\n"
        f"📢 Broadcasts: {bc['total']:,} sent out · {bc['sent']:,} messages delivered")
