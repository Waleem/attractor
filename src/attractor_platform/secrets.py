from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attractor_platform.storage.db import session_scope
from attractor_platform.storage.models import SettingSecretModel

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
            return self._read_existing_key()

        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(self.key_path, flags, 0o600)
        except FileExistsError:
            return self._read_existing_key()
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

    def _read_existing_key(self) -> bytes:
        os.chmod(self.key_path, 0o600)
        return self.key_path.read_bytes()


async def load_provider_secret_values(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    secret_vault: SecretVault,
    provider_names: Iterable[str],
) -> dict[str, str]:
    """Load decrypted provider credentials for runtime use.

    Returned values must stay internal to backend construction and never be
    serialized into settings responses or logs.
    """

    names = tuple(dict.fromkeys(name for name in provider_names if name))
    if not names:
        return {}

    async with session_scope(session_factory) as session:
        secrets = list(
            await session.scalars(
                select(SettingSecretModel).where(SettingSecretModel.name.in_(names))
            )
        )

    return {
        secret.name: secret_vault.decrypt(secret.encrypted_value)
        for secret in secrets
        if secret.name in names
    }
