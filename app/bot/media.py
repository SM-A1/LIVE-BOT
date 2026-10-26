from __future__ import annotations

from io import BytesIO

MAX_MEDIA_PER_BOT = 60


def extract(m):
    """(kind, file_id, filename, size) for the media in a message, or None."""
    if m.photo:
        p = m.photo[-1]
        return "photo", p.file_id, "photo.jpg", p.file_size or 0
    for kind, default in (("video", "video.mp4"), ("document", "file"), ("audio", "audio.mp3"), ("voice", "voice.ogg")):
        obj = getattr(m, kind, None)
        if obj:
            return kind, obj.file_id, getattr(obj, "file_name", None) or default, obj.file_size or 0
    return None


async def store(app, m, bot_id: int, allowed: tuple[str, ...]):
    """Download media sent to the manager bot and keep the bytes (file_ids are not portable between bots)."""
    ex = extract(m)
    if not ex:
        return None, "Please send the file itself (not text)."
    kind, fid, name, size = ex
    if kind not in allowed:
        return None, f"Expected: {', '.join(allowed)}. You sent: {kind}."
    if size > app.settings.media_max_bytes:
        return None, f"File too large (max {app.settings.media_max_bytes // 1024 // 1024} MB)."
    if await app.repos.media.count(bot_id) >= MAX_MEDIA_PER_BOT:
        return None, "This bot reached the media storage limit."
    buf = BytesIO()
    await app.manager_bot.download(fid, destination=buf)
    data = buf.getvalue()
    if len(data) > app.settings.media_max_bytes:
        return None, "File too large."
    return await app.repos.media.add(bot_id, kind, name[:100], data), None
