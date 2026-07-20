"""PJS Cheatsheet — modal z listą kategorii OLX obsługujących Przesyłkę OLX.

Ładuje `data/pjs_categories.json` (przygotowane research agentem).
Fallback do wbudowanej listy gdy JSON brak/uszkodzony.

Otwierane przez button "❓ Pomoc: kategorie PJS" w headerze main_window.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import customtkinter as ctk

from ..config import DB_PATH  # noqa (side-effect: __init__)

__all__ = ["show_pjs_cheatsheet", "load_pjs_categories"]

_LOG = logging.getLogger("marketia.gui.pjs_cheatsheet")

_JSON_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "pjs_categories.json"


def load_pjs_categories() -> dict:
    """Wczytaj JSON. Fallback gdy brak pliku."""
    try:
        return json.loads(_JSON_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        _LOG.warning("pjs_categories.json niedostępne: %s — używam fallback", exc)
        return {
            "_meta": {"version": "fallback", "confidence": "very_low"},
            "categories_with_pjs": [
                {"name": "AGD, Meble, Dom i Ogród", "path": "sprawdź manualnie", "notes": ""},
            ],
            "categories_without_pjs": [
                {"name": "Usługi/Nieruchomości/Motoryzacja/Praca", "reason": "brak fizycznego produktu"},
            ],
            "limitations": {"max_weight_kg": 30},
        }


def show_pjs_cheatsheet(parent: ctk.CTkBaseClass | None = None) -> None:
    """Otwórz modal ze ściągą kategorii PJS."""
    data = load_pjs_categories()

    root = ctk.CTkToplevel(parent) if parent else ctk.CTkToplevel()
    root.title("Kategorie OLX z PJS — ściąga")
    root.geometry("720x680")
    root.minsize(640, 560)
    if parent:
        root.transient(parent)
    root.grab_set()

    # Bottom close button (fixed)
    bottom = ctk.CTkFrame(root, corner_radius=0)
    bottom.pack(side="bottom", fill="x", padx=16, pady=(0, 16))
    ctk.CTkButton(bottom, text="Zamknij", command=root.destroy, width=100).pack(side="right")

    # Scrollable content
    body = ctk.CTkScrollableFrame(root)
    body.pack(fill="both", expand=True, padx=16, pady=16)

    # Header
    ctk.CTkLabel(
        body,
        text="🚚  Kategorie OLX obsługujące PJS",
        font=ctk.CTkFont(size=17, weight="bold"),
    ).pack(anchor="w", pady=(0, 4))

    ctk.CTkLabel(
        body,
        text=(
            "PJS = \"Przesyłka OLX / Zapłać jeśli sprzedasz\". "
            "Nie każda kategoria wspiera tę opcję. Poniżej lista bezpiecznych "
            "kategorii dla dropshippingu."
        ),
        wraplength=640,
        justify="left",
        text_color=("#6b7280", "#9ca3af"),
    ).pack(anchor="w", pady=(0, 12))

    meta = data.get("_meta", {})
    confidence = meta.get("confidence", "unknown")
    if confidence in ("low", "low-pending-research", "very_low"):
        ctk.CTkLabel(
            body,
            text="⚠️  Dane placeholder. Zaktualizuj przez `python -m app.olx.refresh_pjs_categories`.",
            text_color=("#f59e0b", "#fbbf24"),
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", pady=(0, 8))

    # === Categories WITH PJS ===
    _section_header(body, "✅  Z PJS (safe dla dropshippingu)", color=("#059669", "#34d399"))
    for cat in data.get("categories_with_pjs", []):
        _render_category_row(body, cat, ok=True)

    # === Categories WITHOUT PJS ===
    _section_header(body, "❌  Bez PJS", color=("#dc2626", "#f87171"))
    for cat in data.get("categories_without_pjs", []):
        _render_category_row(body, cat, ok=False)

    # === Limitations ===
    _section_header(body, "📏  Ograniczenia PJS", color=("#0284c7", "#38bdf8"))
    limits = data.get("limitations", {})
    _kv_row(body, "Max waga:", f"{limits.get('max_weight_kg', '—')} kg")
    _kv_row(body, "Max rozmiar:", limits.get("max_size_cm", "—"))
    if limits.get("max_value_pln"):
        _kv_row(body, "Max wartość:", f"{limits.get('max_value_pln')} PLN")

    # Size tiers
    tiers = limits.get("size_tiers", {})
    if tiers:
        ctk.CTkLabel(body, text="Rozmiary paczek:", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=16, pady=(8, 2))
        for tier, spec in tiers.items():
            _kv_row(body, f"  {tier}", spec)

    for note in limits.get("other", []):
        ctk.CTkLabel(body, text=f"• {note}", wraplength=640, justify="left", anchor="w", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=1)

    # === Sources ===
    if data.get("sources"):
        _section_header(body, "🔗  Źródła", color=("#6b7280", "#9ca3af"))
        for src in data.get("sources", []):
            ctk.CTkLabel(body, text=f"• {src}", wraplength=640, justify="left", anchor="w", font=ctk.CTkFont(size=11, family="Menlo")).pack(anchor="w", padx=16, pady=1)

    # === Dropshipping notes ===
    if data.get("notes_for_dropshipping"):
        _section_header(body, "💡  Uwagi dla dropshippingu", color=("#7c3aed", "#a78bfa"))
        ctk.CTkLabel(body, text=data["notes_for_dropshipping"], wraplength=640, justify="left", anchor="w").pack(anchor="w", padx=16, pady=(2, 8))


def _section_header(parent, text: str, color=("#111827", "#e5e7eb")):
    ctk.CTkLabel(
        parent,
        text=text,
        font=ctk.CTkFont(size=13, weight="bold"),
        text_color=color,
    ).pack(anchor="w", pady=(16, 6))


def _render_category_row(parent, cat: dict, ok: bool):
    row = ctk.CTkFrame(parent, corner_radius=6, fg_color=("#f0fdf4", "#064e3b") if ok else ("#fef2f2", "#450a0a"))
    row.pack(fill="x", padx=8, pady=2)
    name = cat.get("name", "?")
    path = cat.get("path", "")
    reason_or_notes = cat.get("notes", "") if ok else cat.get("reason", "")
    ctk.CTkLabel(row, text=name, anchor="w", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=12, pady=(6, 0))
    if path:
        ctk.CTkLabel(row, text=path, anchor="w", font=ctk.CTkFont(size=10, family="Menlo"), text_color=("#6b7280", "#9ca3af")).pack(anchor="w", padx=12)
    if reason_or_notes:
        ctk.CTkLabel(row, text=reason_or_notes, anchor="w", wraplength=620, justify="left", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12, pady=(0, 6))


def _kv_row(parent, key: str, value: str):
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", padx=16, pady=1)
    ctk.CTkLabel(row, text=key, width=140, anchor="w", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")
    ctk.CTkLabel(row, text=value, anchor="w", font=ctk.CTkFont(size=11)).pack(side="left")
