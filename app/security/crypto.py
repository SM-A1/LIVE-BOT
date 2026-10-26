from __future__ import annotations

import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken


class TokenVault:
    """Encrypts bot tokens at rest (Fernet = AES-128-CBC + HMAC-SHA256)."""

    def __init__(self, key: str):
        try:
            self._fernet = Fernet(key.encode())
        except Exception:
            raise SystemExit(
                "ENCRYPTION_KEY is not a valid Fernet key. Generate one with: python -m app.security.keygen"
            ) from None
        self._key = key.encode()

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt(self, encrypted: str) -> str:
        try:
            return self._fernet.decrypt(encrypted.encode()).decode()
        except InvalidToken:
            raise ValueError("token decryption failed") from None

    def webhook_secret(self, bot_id: int) -> str:
        return hmac.new(self._key, f"webhook:{bot_id}".encode(), hashlib.sha256).hexdigest()[:48]


def mask_token(token: str) -> str:
    bot_id, _, secret = token.partition(":")
    return f"{bot_id}:••••••{secret[-4:]}"
