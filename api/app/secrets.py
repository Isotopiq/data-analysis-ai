from __future__ import annotations

import base64

from cryptography.fernet import Fernet

from app.settings import settings


def _fernet() -> Fernet:
    # Derive a stable Fernet key from settings.api_secret_key.
    # Note: for production, set a high-entropy random secret.
    raw = settings.api_secret_key.encode("utf-8")
    key = base64.urlsafe_b64encode(raw.ljust(32, b"0")[:32])
    return Fernet(key)


def encrypt_str(value: str) -> bytes:
    return _fernet().encrypt(value.encode("utf-8"))


def decrypt_str(value: bytes) -> str:
    return _fernet().decrypt(value).decode("utf-8")
