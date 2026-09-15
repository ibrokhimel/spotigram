from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from cryptography.fernet import Fernet


def load_fernet(secret: str | None, data_dir: Path) -> Fernet:
    data_dir.mkdir(parents=True, exist_ok=True)
    if secret:
        raw = secret.encode()
        try:
            return Fernet(raw)
        except (ValueError, Exception):
            digest = hashlib.sha256(raw).digest()
            return Fernet(base64.urlsafe_b64encode(digest))
    path = data_dir / "secret.key"
    if path.exists():
        return Fernet(path.read_bytes().strip())
    key = Fernet.generate_key()
    path.write_bytes(key)
    return Fernet(key)


def encrypt_str(fernet: Fernet, value: str) -> str:
    return fernet.encrypt(value.encode()).decode()


def decrypt_str(fernet: Fernet, value: str) -> str:
    return fernet.decrypt(value.encode()).decode()
