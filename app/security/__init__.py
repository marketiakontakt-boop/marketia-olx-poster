"""Security package: Fernet encryption + macOS Keychain (keyring)."""

from .vault import (
    get_or_create_master_key,
    encrypt_dict,
    decrypt_dict,
    save_accounts_encrypted,
    load_accounts_encrypted,
)
from .credentials import get_account_credentials

__all__ = [
    "get_or_create_master_key",
    "encrypt_dict",
    "decrypt_dict",
    "save_accounts_encrypted",
    "load_accounts_encrypted",
    "get_account_credentials",
]
