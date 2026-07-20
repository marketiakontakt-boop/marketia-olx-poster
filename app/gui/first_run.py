"""First-run consent modal — świadoma akceptacja 7 punktów DISCLAIMER.md.

Bez akceptacji aplikacja się nie uruchamia (main.py wywołuje ``sys.exit``).
Consent zapisany w ``data/consent.json`` z timestamp + wersja. Wersja hardcoded
tutaj — bump gdy dodasz nowe punkty do DISCLAIMER.md (user musi re-akceptować).

API:
    has_consent() -> bool
    show_consent_modal() -> bool   # True = akceptacja, False = odrzucenie
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    pass

__all__ = ["has_consent", "show_consent_modal", "CONSENT_VERSION", "CONSENT_PATH"]

_LOG = logging.getLogger("marketia.gui.first_run")

CONSENT_VERSION = "2026-07-17"
CONSENT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "consent.json"

# 7 punktów DISCLAIMER — każdy checkbox blokuje przycisk "Akceptuję świadomie".
DISCLAIMER_ITEMS: tuple[tuple[str, str], ...] = (
    (
        "olx_tos",
        "1. Automatyczne wystawianie ogłoszeń narusza regulamin OLX.pl. "
        "Ryzykuję zablokowaniem konta i utratą aktywnych aukcji.",
    ),
    (
        "multi_account",
        "2. Prowadzenie 3 kont prywatnych narusza regulamin OLX. "
        "Ryzykuję permanent ban wszystkich powiązanych kont.",
    ),
    (
        "playwright_stealth",
        "3. playwright-stealth maskuje sygnały automatyzacji przeglądarki. "
        "W USA może być interpretowane jako CFAA violation. Konsultacja prawna zalecana.",
    ),
    (
        "multi_city_variants",
        "4. Multi-city variants (3-6 miast per produkt) mogą stanowić spam. "
        "Zobowiązuję się do lokacji odpowiadających realnym punktom wysyłki.",
    ),
    (
        "humanizer",
        "5. Humanizer + fingerprint spoofing celowo obchodzą anti-bot OLX. "
        "Ryzyko interpretacji prawnej po mojej stronie.",
    ),
    (
        "captcha_manual",
        "6. CAPTCHA rozwiązuję wyłącznie ręcznie. "
        "Nie próbuję integrować 2captcha ani innych serwisów auto-solving.",
    ),
    (
        "pii_screenshots",
        "7. Screenshoty zawierają PII (numer telefonu, adres, imię/nazwisko). "
        "NIE backupuję output/ do iCloud/Dropbox bez szyfrowania E2E.",
    ),
)


def has_consent() -> bool:
    """Sprawdza czy user zaakceptował DISCLAIMER (raz, permanentnie).

    Decyzja user 2026-07-18: "rozumiem raz ale za każdym razem" — raz zaakceptowane
    = zawsze OK, nawet przy bump wersji DISCLAIMER. Sprawdzamy tylko istnienie
    pliku i pole ``accepted_at``. Wersja + per-item items zostawione w JSON dla
    ewentualnej analizy prawnej ale NIE weryfikowane.
    """
    if not CONSENT_PATH.exists():
        return False
    try:
        with CONSENT_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    # Wystarczy że kiedyś user zaakceptował.
    return bool(data.get("accepted_at"))


def _save_consent() -> None:
    """Zapisuje ``data/consent.json`` z timestamp + all items accepted."""
    CONSENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CONSENT_VERSION,
        "accepted_at": datetime.utcnow().isoformat(),
        "items": {key: True for key, _ in DISCLAIMER_ITEMS},
    }
    with CONSENT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    _LOG.info("Consent saved to %s", CONSENT_PATH)


def show_consent_modal() -> bool:
    """Modal blokujący — user musi zaznaczyć wszystkie 7 punktów.

    Returns:
        True gdy user zaakceptował (wtedy ``consent.json`` zapisany).
        False gdy odmówił / zamknął okno (aplikacja powinna zakończyć się).

    Modal jest własnym CTk (nie Toplevel) — uruchamiany PRZED MainWindow.
    """
    try:
        import customtkinter as ctk
    except ImportError as exc:  # pragma: no cover
        _LOG.error("customtkinter niedostępny: %s", exc)
        return False

    # Own root — modal działa self-contained, MainWindow tworzony dopiero po ok.
    root = ctk.CTk()
    root.title("Marketia OLX Poster — Zgoda użytkownika")
    root.geometry("780x680")
    root.resizable(False, False)

    state = {"accepted": False}
    check_vars: list[tuple[str, "ctk.BooleanVar"]] = []

    ctk.CTkLabel(
        root,
        text="Świadoma akceptacja przed pierwszym uruchomieniem",
        font=ctk.CTkFont(size=17, weight="bold"),
    ).pack(padx=20, pady=(20, 8), anchor="w")

    ctk.CTkLabel(
        root,
        text=(
            "Aplikacja narusza regulamin OLX i może naruszać przepisy prawa. "
            "Przeczytaj DISCLAIMER.md i zaznacz wszystkie 7 punktów."
        ),
        wraplength=740,
        justify="left",
    ).pack(padx=20, pady=(0, 12), anchor="w")

    # Scrollowana ramka z checkboxami (bezpieczne przy dłuższych opisach).
    scroll = ctk.CTkScrollableFrame(root, width=740, height=440)
    scroll.pack(padx=20, pady=(0, 10), fill="both", expand=True)

    for key, text in DISCLAIMER_ITEMS:
        var = ctk.BooleanVar(value=False)
        check_vars.append((key, var))
        # CTkCheckBox nie wspiera wraplength — wraper Frame z krótkim label
        # w checkboxie + długi wrap-owany CTkLabel obok.
        row = ctk.CTkFrame(scroll, fg_color="transparent")
        row.pack(padx=10, pady=6, anchor="w", fill="x")
        ctk.CTkCheckBox(
            row,
            text="",
            variable=var,
            command=lambda: _refresh_button(),
            width=24,
        ).pack(side="left", padx=(0, 10), anchor="n")
        ctk.CTkLabel(
            row,
            text=text,
            wraplength=680,
            justify="left",
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

    bottom = ctk.CTkFrame(root, height=60, corner_radius=0)
    bottom.pack(side="bottom", fill="x")

    status_label = ctk.CTkLabel(
        bottom,
        text="Zaznacz wszystkie 7 punktów, żeby aktywować przycisk.",
        font=ctk.CTkFont(size=11),
    )
    status_label.pack(side="left", padx=20, pady=15)

    def _on_reject() -> None:
        state["accepted"] = False
        root.destroy()

    reject_btn = ctk.CTkButton(
        bottom, text="Odrzucam — zamknij", width=160, command=_on_reject,
        fg_color="#374151", hover_color="#1f2937",
    )
    reject_btn.pack(side="right", padx=(6, 20), pady=12)

    def _on_accept() -> None:
        if not all(v.get() for _, v in check_vars):
            return
        _save_consent()
        state["accepted"] = True
        root.destroy()

    accept_btn = ctk.CTkButton(
        bottom, text="Akceptuję świadomie", width=200, command=_on_accept,
        fg_color="#dc2626", hover_color="#b91c1c", state="disabled",
    )
    accept_btn.pack(side="right", padx=6, pady=12)

    def _refresh_button() -> None:
        checked = sum(1 for _, v in check_vars if v.get())
        total = len(check_vars)
        if checked == total:
            accept_btn.configure(state="normal")
            status_label.configure(text=f"Zaznaczono {checked}/{total} — możesz zaakceptować.")
        else:
            accept_btn.configure(state="disabled")
            status_label.configure(text=f"Zaznaczono {checked}/{total} — brakuje {total - checked}.")

    root.protocol("WM_DELETE_WINDOW", _on_reject)
    root.mainloop()

    return state["accepted"]
