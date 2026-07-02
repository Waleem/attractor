from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet

DEFAULT_SECRET_KEY_PATH = Path("~/.attractor/platform-secret.key")
SECRET_KEY_PATH_ENV = "ATTRACTOR_SECRET_KEY_PATH"


class SecretVault:
    """Small Fernet wrapper for write-only platform secrets."""

    def __init__(self, key_path: str | Path | None = None) -> None:
        self.key_path = self._resolve_key_path(key_path)
        self._fernet: Fernet | None = None

    def encrypt(self, value: str) -> str:
        if not value:
            raise ValueError("Secret value must not be empty")
        return self._get_fernet().encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._get_fernet().decrypt(token.encode("ascii")).decode("utf-8")

    @staticmethod
    def _resolve_key_path(key_path: str | Path | None) -> Path:
        configured_path = key_path or os.environ.get(SECRET_KEY_PATH_ENV) or DEFAULT_SECRET_KEY_PATH
        return Path(configured_path).expanduser().resolve()

    def _get_fernet(self) -> Fernet:
        if self._fernet is None:
            self._fernet = Fernet(self._load_or_create_key())
        return self._fernet

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            return self.key_path.read_bytes()

        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(self.key_path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(key)
        except Exception:
            try:
                self.key_path.unlink()
            except OSError:
                pass
            raise
        os.chmod(self.key_path, 0o600)
        return key
