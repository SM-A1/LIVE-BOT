"""Structured JSON logging with automatic secret redaction."""
from __future__ import annotations

import json
import logging
import re
import sys
import time

TOKEN_RE = re.compile(r"\d{5,12}:[A-Za-z0-9_-]{30,}")
_secrets: list[str] = []
_log = logging.getLogger("app")


def register_secret(value: str) -> None:
    if value and len(value) >= 8:
        _secrets.append(value)


def redact(text: str) -> str:
    text = TOKEN_RE.sub("[redacted-token]", text)
    for s in _secrets:
        text = text.replace(s, "[redacted]")
    return text


class JsonFormatter(logging.Formatter):
    FIELDS = ("user_id", "bot_id", "action", "status", "error_code")

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for f in self.FIELDS:
            if getattr(record, f, None) is not None:
                data[f] = getattr(record, f)
        if record.exc_info:
            data["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(data, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level, logging.INFO))
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def log_event(action: str, status: str = "ok", *, user_id=None, bot_id=None, error_code=None, msg: str = "",
              level: int = logging.INFO) -> None:
    _log.log(level, msg or action, extra={"action": action, "status": status, "user_id": user_id,
                                          "bot_id": bot_id, "error_code": error_code})
