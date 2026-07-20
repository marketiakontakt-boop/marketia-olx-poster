"""Account Panel — tab "Konta".

GUI dla:
  - listy zdefiniowanych kont (status icon, email, miasta, slot, warmup, status)
  - wizard "+ Dodaj konto" (encrypt password → Keychain, cfg → Fernet vault)
  - edit istniejącego (nazwa disabled — jest PK w vault)
  - delete konta (confirm modal + osobno delete password z Keychain)

Security:
  - Password NIGDY w JSON — tylko referencja `keychain://name`
  - Password w Keychain: service=KEYCHAIN_SERVICE, username=`password:{name}`
  - Wizard entry z `show="*"` — nie widoczne w GUI
"""
from __future__ import annotations

import logging
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk
import keyring

from ..config import (
    ACCOUNTS_ENCRYPTED_PATH,
    DEFAULT_DAILY_LIMIT,
    DEFAULT_WARMUP_DAYS,
    KEYCHAIN_SERVICE,
    PROFILES_DIR,
)
from ..data.shared_db import get_or_create_account_meta
from ..olx.city_variants import get_all_cities
from ..security.vault import (
    VaultError,
    load_accounts_encrypted,
    save_accounts_encrypted,
)

__all__ = ["AccountPanel", "AccountWizardDialog"]

_LOG = logging.getLogger("marketia.gui.account_panel")

SLOT_CHOICES: list[tuple[str, str]] = [
    ("08:00-11:30 (rano)", "08:00-11:30"),
    ("14:00-17:30 (popoludnie)", "14:00-17:30"),
    ("19:00-22:00 (wieczor)", "19:00-22:00"),
]


class AccountPanel(ctk.CTkFrame):
    """Tab Konta."""

    def __init__(
        self,
        parent: ctk.CTkBaseClass,
        on_action: Callable[..., None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_action = on_action
        self._accounts: dict[str, dict[str, Any]] = {}
        self._build()
        self._refresh()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Konta OLX",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            header,
            text="+ Dodaj konto",
            width=140,
            command=lambda: self._open_wizard(),
        ).grid(row=0, column=1, padx=4)
        ctk.CTkButton(
            header,
            text="Odswiez",
            width=90,
            fg_color="transparent",
            border_width=1,
            command=self._refresh,
        ).grid(row=0, column=2, padx=4)

        self._list_frame = ctk.CTkScrollableFrame(self)
        self._list_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def _refresh(self) -> None:
        # destroy children
        for child in self._list_frame.winfo_children():
            child.destroy()

        # learning: CTkScrollableFrame yview_moveto po rebuild
        try:
            self.after(0, lambda: self._list_frame._parent_canvas.yview_moveto(0))
        except Exception:  # pragma: no cover
            pass

        try:
            self._accounts = load_accounts_encrypted(ACCOUNTS_ENCRYPTED_PATH)
        except FileNotFoundError:
            self._accounts = {}
        except VaultError as exc:
            _LOG.error("Failed to load accounts: %s", exc)
            self._accounts = {}

        if not self._accounts:
            ctk.CTkLabel(
                self._list_frame,
                text="Brak kont. Kliknij [+ Dodaj konto] zeby dodac pierwsze.",
                anchor="center",
            ).pack(expand=True, pady=40)
            return

        for name, cfg in self._accounts.items():
            self._render_account_card(name, cfg)

    def _render_account_card(self, name: str, cfg: dict[str, Any]) -> None:
        card = ctk.CTkFrame(self._list_frame, corner_radius=8)
        card.pack(fill="x", padx=4, pady=4)
        card.grid_columnconfigure(0, weight=1)

        try:
            meta = get_or_create_account_meta(name)
        except Exception:  # pragma: no cover
            traceback.print_exc(file=sys.stdout)
            meta = None

        is_paused = bool(meta["is_paused"]) if meta else False
        warmup_remaining = int(meta["warmup_days_remaining"]) if meta else 0
        pause_reason = meta["pause_reason"] if meta and meta["pause_reason"] else "-"

        status_icon = "[PAUZA]" if is_paused else ("[WARMUP]" if warmup_remaining > 0 else "[OK]")

        header_row = ctk.CTkFrame(card, fg_color="transparent")
        header_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        header_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header_row,
            text=f"{status_icon}  {name}",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            header_row,
            text="Edytuj",
            width=72,
            command=lambda n=name: self._open_wizard(edit=n),
        ).grid(row=0, column=1, padx=2)
        ctk.CTkButton(
            header_row,
            text="Usun",
            width=64,
            fg_color=("#dc2626", "#991b1b"),
            hover_color=("#ef4444", "#7f1d1d"),
            command=lambda n=name: self._delete_account(n),
        ).grid(row=0, column=2, padx=2)

        details = ctk.CTkFrame(card, fg_color="transparent")
        details.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        details.grid_columnconfigure(1, weight=1)

        rows = [
            ("Email:", cfg.get("email", "-")),
            ("Telefon:", cfg.get("phone", "-")),
            ("Miasta:", ", ".join(cfg.get("cities_assigned", [])) or "-"),
            ("Slot:", cfg.get("slot", "-")),
            (
                "Limit dnia:",
                f"{cfg.get('daily_limit', 0)}  (warmup: {warmup_remaining}/{DEFAULT_WARMUP_DAYS} dni)",
            ),
            ("Status:", "Aktywne" if not is_paused else f"Pauza: {pause_reason}"),
        ]
        for i, (label, value) in enumerate(rows):
            ctk.CTkLabel(
                details,
                text=label,
                font=ctk.CTkFont(size=11),
                text_color=("#6b7280", "#9ca3af"),
                anchor="w",
                width=100,
            ).grid(row=i, column=0, sticky="w", padx=(0, 8))
            ctk.CTkLabel(
                details,
                text=str(value),
                font=ctk.CTkFont(size=11),
                anchor="w",
            ).grid(row=i, column=1, sticky="w")

    def _open_wizard(self, edit: str | None = None) -> None:
        dlg = AccountWizardDialog(self, existing_name=edit, on_saved=self._refresh)
        dlg.focus()

    def _delete_account(self, name: str) -> None:
        # Confirm modal — user musi wpisać nazwę konta
        confirm = ctk.CTkInputDialog(
            text=f"Wpisz '{name}' zeby potwierdzic usuniecie:",
            title="Potwierdzenie usuniecia",
        )
        entered = confirm.get_input()
        if entered != name:
            _LOG.info("delete cancelled: entered=%r expected=%r", entered, name)
            return

        # Delete z vault
        try:
            accounts = load_accounts_encrypted(ACCOUNTS_ENCRYPTED_PATH)
        except FileNotFoundError:
            accounts = {}
        accounts.pop(name, None)
        save_accounts_encrypted(accounts, ACCOUNTS_ENCRYPTED_PATH)

        # Delete password z Keychain
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, f"password:{name}")
        except keyring.errors.PasswordDeleteError:
            _LOG.debug("delete_password: no entry for %s (already deleted?)", name)
        except Exception:  # pragma: no cover
            traceback.print_exc(file=sys.stdout)

        _LOG.info("Deleted account: %s", name)
        self._refresh()


class AccountWizardDialog(ctk.CTkToplevel):
    """Modal do dodawania/edycji konta."""

    def __init__(
        self,
        parent: ctk.CTkBaseClass,
        existing_name: str | None = None,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title(
            "Nowe konto OLX"
            if not existing_name
            else f"Edycja konta: {existing_name}"
        )
        # learning: CTkToplevel geometry musi mieć zapas
        self.geometry("560x740")
        self.minsize(520, 640)
        self.transient(parent)
        try:
            self.grab_set()
        except Exception:  # pragma: no cover
            pass

        self._existing_name = existing_name
        self._on_saved = on_saved
        self._entries: dict[str, ctk.CTkEntry] = {}
        self._city_vars: dict[str, ctk.BooleanVar] = {}

        self._build()

        if self._existing_name:
            self._prefill()

    def _build(self) -> None:
        # Fixed-bottom buttons (learning: pack side=bottom PRZED CTkScrollableFrame)
        buttons = ctk.CTkFrame(self)
        buttons.pack(side="bottom", fill="x", padx=12, pady=12)
        ctk.CTkButton(buttons, text="Zapisz", command=self._save).pack(
            side="right", padx=4
        )
        ctk.CTkButton(
            buttons,
            text="Anuluj",
            command=self.destroy,
            fg_color="transparent",
            border_width=1,
        ).pack(side="right", padx=4)

        # Scrollable form
        form = ctk.CTkScrollableFrame(self)
        form.pack(fill="both", expand=True, padx=12, pady=(12, 0))

        self._build_field(form, "name", "Nazwa (unikalna):")
        self._build_field(form, "email", "Email:")
        self._build_field(form, "password", "Haslo:", show="*")
        self._build_field(form, "phone", "Telefon:")

        # Miasta (multi-select checkboxes)
        ctk.CTkLabel(
            form, text="Miasta przypisane:", anchor="w"
        ).pack(anchor="w", padx=8, pady=(12, 4))
        cities_frame = ctk.CTkFrame(form, fg_color="transparent")
        cities_frame.pack(fill="x", padx=8, pady=(0, 8))
        cities = get_all_cities()
        if not cities:
            ctk.CTkLabel(
                cities_frame,
                text="(brak city_templates.json — sprawdz data/city_templates.json)",
                text_color=("#f59e0b", "#fbbf24"),
                font=ctk.CTkFont(size=10),
            ).pack(anchor="w", padx=4, pady=2)
        else:
            for c in cities:
                v = ctk.BooleanVar()
                cb = ctk.CTkCheckBox(cities_frame, text=c, variable=v)
                cb.pack(anchor="w", padx=4, pady=2)
                self._city_vars[c] = v

        # Slot dropdown (radio)
        ctk.CTkLabel(form, text="Slot dziennego okna:", anchor="w").pack(
            anchor="w", padx=8, pady=(12, 4)
        )
        self._slot_var = ctk.StringVar(value=SLOT_CHOICES[0][1])
        for label, val in SLOT_CHOICES:
            ctk.CTkRadioButton(
                form, text=label, variable=self._slot_var, value=val
            ).pack(anchor="w", padx=16, pady=2)

        # Warmup + limit
        self._build_field(
            form, "warmup_days", "Warmup dni:", default=str(DEFAULT_WARMUP_DAYS)
        )
        self._build_field(
            form,
            "daily_limit",
            "Limit dzienny:",
            default=str(DEFAULT_DAILY_LIMIT),
        )

        # Proxy field + warning
        proxy_frame = ctk.CTkFrame(form)
        proxy_frame.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(
            proxy_frame, text="Proxy (opcjonalne):", anchor="w"
        ).pack(anchor="w", padx=8, pady=(8, 4))
        self._entries["proxy"] = ctk.CTkEntry(
            proxy_frame, placeholder_text="socks5://user:pass@host:port"
        )
        self._entries["proxy"].pack(fill="x", padx=8, pady=(0, 4))
        ctk.CTkLabel(
            proxy_frame,
            text="UWAGA: user zdecydowal SKIP proxy — zostaw puste.",
            text_color=("#f59e0b", "#fbbf24"),
            font=ctk.CTkFont(size=10),
        ).pack(anchor="w", padx=8, pady=(0, 8))

        # dev_login checkbox
        self._devlogin_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            form,
            text="Uruchom dev_login po zapisaniu (zaloguj sie recznie w otwartym browserze)",
            variable=self._devlogin_var,
        ).pack(anchor="w", padx=8, pady=12)

    def _build_field(
        self,
        parent: ctk.CTkBaseClass,
        key: str,
        label: str,
        default: str = "",
        show: str | None = None,
    ) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(row, text=label, width=150, anchor="w").pack(side="left")
        entry = ctk.CTkEntry(row, show=show)
        if default:
            entry.insert(0, default)
        entry.pack(side="left", fill="x", expand=True)
        self._entries[key] = entry

    def _save(self) -> None:
        name = self._entries["name"].get().strip()
        if not name:
            self._error("Podaj nazwe konta")
            return
        # Walidacja: unikalna nazwa (przy add — istniejące odrzuca)
        try:
            existing_accounts = load_accounts_encrypted(ACCOUNTS_ENCRYPTED_PATH)
        except FileNotFoundError:
            existing_accounts = {}
        if not self._existing_name and name in existing_accounts:
            self._error(f"Konto '{name}' juz istnieje. Uzyj Edytuj.")
            return

        password = self._entries["password"].get()
        # Edit: puste hasło = zachowaj obecne
        if not self._existing_name and not password:
            self._error("Podaj haslo (wymagane przy dodawaniu nowego konta)")
            return

        try:
            warmup_days = int(self._entries["warmup_days"].get() or DEFAULT_WARMUP_DAYS)
            daily_limit = int(self._entries["daily_limit"].get() or DEFAULT_DAILY_LIMIT)
        except ValueError:
            self._error("Warmup dni i limit dzienny musza byc liczbami")
            return

        cfg: dict[str, Any] = {
            "email": self._entries["email"].get().strip(),
            "phone": self._entries["phone"].get().strip(),
            "user_data_dir": str(PROFILES_DIR / name),
            "cities_assigned": [c for c, v in self._city_vars.items() if v.get()],
            "slot": self._slot_var.get(),
            "daily_limit": daily_limit,
            "proxy": self._entries["proxy"].get().strip() or None,
            "password_ref": f"keychain://{name}",
        }

        # Password → Keychain OSOBNO (nigdy w JSON)
        if password:
            try:
                keyring.set_password(KEYCHAIN_SERVICE, f"password:{name}", password)
            except Exception as exc:  # pragma: no cover
                traceback.print_exc(file=sys.stdout)
                self._error(f"Nie udalo sie zapisac hasla w Keychain: {exc}")
                return

        # Save do encrypted vault
        existing_accounts[name] = cfg
        try:
            save_accounts_encrypted(existing_accounts, ACCOUNTS_ENCRYPTED_PATH)
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            self._error(f"Nie udalo sie zapisac vault: {exc}")
            return

        # Setup meta (warmup) — idempotent
        try:
            get_or_create_account_meta(name, warmup_days=warmup_days)
        except Exception:  # pragma: no cover
            traceback.print_exc(file=sys.stdout)

        _LOG.info(
            "Saved account: %s (warmup=%d, cities=%s, slot=%s)",
            name,
            warmup_days,
            cfg["cities_assigned"],
            cfg["slot"],
        )

        if self._on_saved:
            try:
                self._on_saved()
            except Exception:  # pragma: no cover
                traceback.print_exc(file=sys.stdout)

        if self._devlogin_var.get():
            self._launch_dev_login(name)

        self.destroy()

    def _launch_dev_login(self, name: str) -> None:
        """Odpala dev_login w NOWYM oknie Terminal (user widzi progress + browser)."""
        try:
            project_root = Path(__file__).resolve().parents[2]
            py = sys.executable
            # AppleScript escape (bash w cudzysłowach, escape " i \)
            cmd = f'cd \\"{project_root}\\" && \\"{py}\\" -m app.olx.login_manager dev_login \\"{name}\\"'
            applescript = (
                f'tell application "Terminal"\n'
                f'    activate\n'
                f'    do script "{cmd}"\n'
                f'end tell'
            )
            subprocess.Popen(["osascript", "-e", applescript])
            _LOG.info("dev_login launched in new Terminal for %s", name)

            # Info modal — user musi wiedzieć że browser się otworzy
            import tkinter.messagebox as mb
            mb.showinfo(
                "Dev login uruchomiony",
                f"Otworzyłem nowe okno Terminala + Chrome dla konta '{name}'.\n\n"
                f"1. Poczekaj aż OLX się załaduje w Chrome (~3-5s)\n"
                f"2. Zaakceptuj cookies\n"
                f"3. Wpisz email + hasło + kliknij 'Zaloguj się'\n"
                f"4. Po sukcesie Chrome i Terminal się zamkną same\n\n"
                f"Progress widoczny w oknie Terminala."
            )
        except Exception as exc:  # pragma: no cover
            traceback.print_exc(file=sys.stdout)
            _LOG.warning("dev_login launch failed for %s: %s", name, exc)
            import tkinter.messagebox as mb
            mb.showerror("Blad dev_login", str(exc))

    def _error(self, msg: str) -> None:
        import tkinter.messagebox as mb

        mb.showerror("Blad", msg)

    def _prefill(self) -> None:
        try:
            accounts = load_accounts_encrypted(ACCOUNTS_ENCRYPTED_PATH)
        except (FileNotFoundError, VaultError):
            return
        cfg = accounts.get(self._existing_name or "", {})
        for key in ("email", "phone", "proxy"):
            val = cfg.get(key)
            if val:
                self._entries[key].delete(0, "end")
                self._entries[key].insert(0, str(val))

        # Nazwa disabled po prefill (edit nie pozwala zmienić PK)
        self._entries["name"].delete(0, "end")
        self._entries["name"].insert(0, self._existing_name or "")
        self._entries["name"].configure(state="disabled")

        for c in cfg.get("cities_assigned", []):
            if c in self._city_vars:
                self._city_vars[c].set(True)

        if "slot" in cfg:
            self._slot_var.set(cfg["slot"])
        if "daily_limit" in cfg:
            self._entries["daily_limit"].delete(0, "end")
            self._entries["daily_limit"].insert(0, str(cfg["daily_limit"]))

        # Password field placeholder — user może zostawić puste żeby zachować
        self._entries["password"].configure(placeholder_text="(zostaw puste = bez zmiany)")
