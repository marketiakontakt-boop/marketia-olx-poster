"""Unit testy dla app/security/vault.py — Fernet + mock keyring."""
from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.security.vault import (
    VaultError,
    decrypt_dict,
    encrypt_dict,
    get_or_create_master_key,
    load_accounts_encrypted,
    save_accounts_encrypted,
)


class TestMasterKey:
    def test_generates_key_first_call(self, mock_keyring):
        assert not mock_keyring
        key = get_or_create_master_key()
        assert isinstance(key, bytes)
        assert len(key) == 44  # Fernet.generate_key() → 44 znaki base64
        assert len(mock_keyring) == 1

    def test_returns_same_key_on_second_call(self, mock_keyring):
        k1 = get_or_create_master_key()
        k2 = get_or_create_master_key()
        assert k1 == k2


class TestEncryptDecrypt:
    def test_roundtrip_simple(self, mock_keyring):
        data = {"user": "jakub", "count": 3}
        cipher = encrypt_dict(data)
        assert isinstance(cipher, bytes)
        assert cipher != b""
        assert decrypt_dict(cipher) == data

    def test_roundtrip_polish_diacritics(self, mock_keyring):
        data = {"city": "Kraków", "phone": "+48 500 600 700", "note": "żółć"}
        assert decrypt_dict(encrypt_dict(data)) == data

    def test_roundtrip_nested(self, mock_keyring):
        data = {"accounts": [{"email": "a@b.pl", "cities": ["Warszawa", "Łódź"]}]}
        assert decrypt_dict(encrypt_dict(data)) == data

    def test_decrypt_wrong_key_raises_vault_error(self, mock_keyring):
        cipher = encrypt_dict({"x": 1})
        # Podmień master key — nowy Fernet nie odczyta poprzedniego cipher.
        mock_keyring.clear()
        _ = get_or_create_master_key()  # regeneruje nowy
        with pytest.raises(VaultError, match="Nieprawidłowy token"):
            decrypt_dict(cipher)

    def test_decrypt_garbage_raises(self, mock_keyring):
        _ = get_or_create_master_key()
        with pytest.raises(VaultError):
            decrypt_dict(b"not-a-valid-fernet-token")

    def test_decrypt_valid_fernet_but_not_json_raises(self, mock_keyring):
        # Zaszyfruj plaintext który nie jest JSON.
        _ = get_or_create_master_key()
        # Użyj tego samego master key co vault.
        raw_key_str = list(mock_keyring.values())[0]
        f = Fernet(raw_key_str.encode("utf-8"))
        cipher = f.encrypt(b"this is not json {")
        with pytest.raises(VaultError, match="nie jest JSON"):
            decrypt_dict(cipher)


class TestSaveLoadAccounts:
    def test_save_creates_encrypted_file(self, mock_keyring, tmp_path: Path):
        path = tmp_path / "sub" / "accounts.json.encrypted"
        data = {"acc1": "secret"}
        save_accounts_encrypted(data, path)
        assert path.exists()
        assert path.read_bytes() != b'{"acc1": "secret"}'  # zaszyfrowane

    def test_save_and_load_roundtrip(self, mock_keyring, tmp_path: Path):
        path = tmp_path / "accounts.json.encrypted"
        data = {"acc1": {"email": "x@y.pl", "password": "p1"}}
        save_accounts_encrypted(data, path)
        assert load_accounts_encrypted(path) == data

    def test_save_is_atomic_via_tmp_rename(self, mock_keyring, tmp_path: Path):
        path = tmp_path / "accounts.json.encrypted"
        save_accounts_encrypted({"k": 1}, path)
        # Po zapisie plik .tmp NIE powinien istnieć (został rename'owany).
        assert not path.with_suffix(path.suffix + ".tmp").exists()

    def test_load_missing_file_raises(self, mock_keyring, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_accounts_encrypted(tmp_path / "nope.encrypted")

    def test_load_expands_user(self, mock_keyring, tmp_path: Path, monkeypatch):
        # Symuluj że ~ rozwija się do tmp_path
        monkeypatch.setenv("HOME", str(tmp_path))
        path = tmp_path / "accounts.json.encrypted"
        save_accounts_encrypted({"a": 1}, path)
        assert load_accounts_encrypted(Path("~/accounts.json.encrypted")) == {"a": 1}
