"""Ładowanie credentials konkretnego konta z zaszyfrowanego pliku."""
from __future__ import annotations

from typing import Any

from ..config import ACCOUNTS_ENCRYPTED_PATH
from .vault import load_accounts_encrypted

__all__ = ["get_account_credentials", "CredentialsNotFound"]


class CredentialsNotFound(KeyError):
    """Rzucane gdy konto o tej nazwie nie istnieje w vault."""


def get_account_credentials(name: str) -> dict[str, Any]:
    """Zwraca dict credentials dla konta.

    Rzuca:
        FileNotFoundError — gdy accounts.json.encrypted nie istnieje.
        CredentialsNotFound — gdy `name` nieznane w vault.
        VaultError — gdy master key nie pasuje.
    """
    accounts = load_accounts_encrypted(ACCOUNTS_ENCRYPTED_PATH)
    if name not in accounts:
        raise CredentialsNotFound(
            f"Konto '{name}' nie istnieje w vault "
            f"(dostępne: {sorted(accounts.keys())})"
        )
    return accounts[name]
