from __future__ import annotations

import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

import attractor_platform.secrets as secrets_module
from attractor_platform.secrets import SecretVault


def test_secret_vault_creates_fernet_key_with_owner_only_permissions(tmp_path: Path) -> None:
    key_path = tmp_path / "platform-secret.key"

    vault = SecretVault(key_path=key_path)
    encrypted = vault.encrypt("sk-test-secret")

    assert encrypted != "sk-test-secret"
    assert vault.decrypt(encrypted) == "sk-test-secret"
    if hasattr(stat, "S_IMODE"):
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_secret_vault_reuses_existing_key_for_later_instances(tmp_path: Path) -> None:
    key_path = tmp_path / "platform-secret.key"
    first = SecretVault(key_path=key_path)
    encrypted = first.encrypt("replaceable")

    second = SecretVault(key_path=key_path)

    assert second.decrypt(encrypted) == "replaceable"


def test_secret_vault_hardens_existing_key_permissions(tmp_path: Path) -> None:
    key_path = tmp_path / "platform-secret.key"
    original = SecretVault(key_path=key_path)
    encrypted = original.encrypt("existing-key")
    key_path.chmod(0o644)

    hardened = SecretVault(key_path=key_path)

    assert hardened.decrypt(encrypted) == "existing-key"
    if hasattr(stat, "S_IMODE"):
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_secret_vault_rereads_key_when_first_create_loses_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_path = tmp_path / "platform-secret.key"
    raced_key = Fernet.generate_key()

    def raise_after_racing_key_into_place(
        path: str | bytes,
        flags: int,
        mode: int = 0o777,
    ) -> int:
        key_path.write_bytes(raced_key)
        key_path.chmod(0o644)
        raise FileExistsError(path)

    monkeypatch.setattr(secrets_module.os, "open", raise_after_racing_key_into_place)

    vault = SecretVault(key_path=key_path)
    encrypted = vault.encrypt("race-winner-key")

    assert vault.decrypt(encrypted) == "race-winner-key"
    if hasattr(stat, "S_IMODE"):
        assert stat.S_IMODE(key_path.stat().st_mode) == 0o600


def test_secret_vault_rejects_empty_secret_values(tmp_path: Path) -> None:
    vault = SecretVault(key_path=tmp_path / "platform-secret.key")

    with pytest.raises(ValueError, match="Secret value must not be empty"):
        vault.encrypt("")
