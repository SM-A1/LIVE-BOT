from __future__ import annotations

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.services.variables import render

SEND = {"photo": "send_photo", "video": "send_video", "document": "send_document",
        "audio": "send_audio", "voice": "send_voice"}


def build_markup(rows) -> InlineKeyboardMarkup | None:
    kb = []
    for row in rows or []:
        line = []
        for b in row:
            k, v, label = b["kind"], b["value"], b["label"]
            if k == "url":
                line.append(InlineKeyboardButton(text=label, url=v))
            elif k in ("callback", "command"):
                line.append(InlineKeyboardButton(text=label, callback_data=("u:" + v)[:62]))
            elif k == "web_app":
                line.append(InlineKeyboardButton(text=label, web_app=WebAppInfo(url=v)))
            elif k == "switch_inline":
                line.append(InlineKeyboardButton(text=label, switch_inline_query=v))
        if line:
            kb.append(line)
    return InlineKeyboardMarkup(inline_keyboard=kb) if kb else None


def build_script_markup(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=l, url=u) for l, u in r] for r in rows])


async def _html_or_plain(fn, html_text: str, plain_text: str):
    try:
        return await fn(html_text, ParseMode.HTML)
    except TelegramBadRequest as exc:
        if "parse entities" in str(exc).lower():
            return await fn(plain_text, None)
        raise


def _file_id(msg, kind: str) -> str | None:
    obj = getattr(msg, kind, None)
    if kind == "photo":
        return obj[-1].file_id if obj else None
    return getattr(obj, "file_id", None)


async def send_rich(rt, repos, chat_id: int, text: str, values: dict, media=None, rows=None):
    """Send text or media with variables, buttons, HTML->plain fallback and per-bot outbound pacing."""
    markup = build_markup(rows)
    html_t, plain_t = render(text, values, True), render(text, values, False)
    await rt.pacer.wait()
    if not media:
        return await _html_or_plain(
            lambda t, pm: rt.bot.send_message(chat_id, t or "…", parse_mode=pm, reply_markup=markup,
                                              disable_web_page_preview=True), html_t, plain_t)
    kind = media["kind"]
    method = getattr(rt.bot, SEND[kind])
    short = len(plain_t) <= 1024

    async def go(file, with_markup=True):
        async def call(t, pm):
            return await method(chat_id, **{kind: file}, caption=(t if short else None) or None, parse_mode=pm,
                                reply_markup=markup if short and with_markup else None)
        return await _html_or_plain(call, html_t, plain_t)

    msg = None
    if media["tg_file_id"]:
        try:
            msg = await go(media["tg_file_id"])
        except TelegramBadRequest as exc:
            if "file" not in str(exc).lower():
                raise
    if msg is None:
        blob = await repos.media.data(rt.id, media["id"])
        if not blob:
            return await send_rich(rt, repos, chat_id, text, values, None, rows)
        msg = await go(BufferedInputFile(bytes(blob["data"]), filename=blob["filename"]))
        fid = _file_id(msg, kind)
        if fid:
            await repos.media.set_file_id(media["id"], fid)
    if not short:  # caption limit is 1024: send long text separately
        await rt.pacer.wait()
        await _html_or_plain(lambda t, pm: rt.bot.send_message(chat_id, t, parse_mode=pm, reply_markup=markup),
                             html_t, plain_t)
    return msg
