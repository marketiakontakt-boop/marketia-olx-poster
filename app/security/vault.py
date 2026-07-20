"""Vault: Fernet (AES-128) + macOS Keychain via ``keyring``.

Master key generowany jednorazowo i trzymany w Keychain. Wszystkie sekretne
pliki (``accounts.json.encrypted``) są szyfrowane tym kluczem.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import keyring
from cryptography.fernet import Fernet, InvalidToken

from ..config import KEYCHAIN_MASTER_KEY_USERNAME, KEYCHAIN_SERVICE

__all__ = [
    "get_or_create_master_key",
    "encrypt_dict",
    "decrypt_dict",
    "save_accounts_encrypted",
    "load_accounts_encrypted",
    "VaultError",
]


class VaultError(RuntimeError):
    """Rzucane przy problemach z Keychain / Fernet."""


def get_or_create_master_key() -> bytes:
    """Zwraca master key z Keychain. Generuje + zapisuje przy pierwszym użyciu.

    Klucz to bytes zwrócone przez ``Fernet.generate_key()`` (44 znaki base64).
    """
    stored = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_MASTER_KEY_USERNAME)
    if stored:
        return stored.encode("utf-8")

    new_key = Fernet.generate_key()
    keyring.set_password(
        KEYCHAIN_SERVICE,
        KEYCHAIN_MASTER_KEY_USERNAME,
        new_key.decode("utf-8"),
    )
    return new_key


def _fernet() -> Fernet:
    return Fernet(get_or_create_master_key())


def encrypt_dict(data: dict[str, Any]) -> bytes:
    """JSON-serializuje dict i szyfruje Fernet-em."""
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return _fernet().encrypt(payload)


def decrypt_dict(cipher: bytes) -> dict[str, Any]:
    """Odszyfrowuje bytes → JSON → dict. Rzuca VaultError przy złym cipher."""
    try:
        raw = _fernet().decrypt(cipher)
    except InvalidToken as exc:
        raise VaultError("Nieprawidłowy token — zły master key lub uszkodzony plik.") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise VaultError(f"Odszyfrowana zawartość nie jest JSON: {exc}") from exc


def save_accounts_encrypted(data: dict[str, Any], path: Path) -> None:
    """Zapis atomiczny (tmp + rename) — nie zostawia półzapisu przy crashu."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(encrypt_dict(data))
    tmp.replace(path)


def load_accounts_encrypted(path: Path) -> dict[str, Any]:
    """Wczytuje i deszyfruje. Rzuca FileNotFoundError gdy plik brakuje."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Plik nie istnieje: {path}")
    return decrypt_dict(path.read_bytes())
