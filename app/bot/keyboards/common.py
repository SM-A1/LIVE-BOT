from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def kb(rows: list, back: str = "home") -> InlineKeyboardMarkup:
    """Every screen ends with ⬅️ Back and 🏠 Main Menu."""
    rows = [r for r in rows if r]
    rows.append([b("⬅️ Back", back), b("🏠 Main Menu", "home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pager(prefix: str, page: int, total: int, per: int) -> list:
    last = max((total - 1) // per, 0)
    row = []
    if page > 0:
        row.append(b("◀️", f"{prefix}:{page - 1}"))
    if last:
        row.append(b(f"{page + 1}/{last + 1}", "noop:page"))
    if page < last:
        row.append(b("▶️", f"{prefix}:{page + 1}"))
    return row
