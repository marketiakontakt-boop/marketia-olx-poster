"""City Config — tab "Miasta".

Faza 4 stub: read-only display 7 miast z `data/city_templates.json`.
Full edit UI odłożone do Fazy 5 buffer (add/remove/edit location_variants,
price_offset, description_addon inline).
"""
from __future__ import annotations

import json
import logging

import customtkinter as ctk

from ..config import CITY_TEMPLATES_PATH

__all__ = ["CityConfig"]

_LOG = logging.getLogger("marketia.gui.city_config")


class CityConfig(ctk.CTkFrame):
    """Tab Miasta — read-only lista 7 miast."""

    def __init__(self, parent: ctk.CTkBaseClass):
        super().__init__(parent)
        self._build()
        self._refresh()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ctk.CTkLabel(
            header,
            text="Miasta (templates)",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(anchor="w", padx=8, pady=4)
        ctk.CTkLabel(
            header,
            text="Faza 4 stub: read-only. Full editor w Fazie 5.",
            text_color=("#6b7280", "#9ca3af"),
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=8)

        self._list_frame = ctk.CTkScrollableFrame(self)
        self._list_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def _refresh(self):
        for child in self._list_frame.winfo_children():
            child.destroy()
        self.after(0, lambda: self._list_frame._parent_canvas.yview_moveto(0))

        try:
            payload = json.loads(CITY_TEMPLATES_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            _LOG.error("Failed to load city_templates.json: %s", exc)
            ctk.CTkLabel(self._list_frame, text=f"Brak pliku: {CITY_TEMPLATES_PATH}\n{exc}").pack(pady=20)
            return

        cities = payload.get("cities", {})
        for name, cfg in cities.items():
            self._render_city_card(name, cfg)

    def _render_city_card(self, name: str, cfg: dict):
        card = ctk.CTkFrame(self._list_frame, corner_radius=8)
        card.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(
            card,
            text=f"📍 {name}",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(8, 2))
        details = [
            ("Suffix:", cfg.get("title_suffix", "-")),
            ("Addon:", (cfg.get("description_addon", "-")[:80] + "…") if len(cfg.get("description_addon", "")) > 80 else cfg.get("description_addon", "-")),
            ("Dzielnice:", ", ".join(cfg.get("location_variants", [])[:3]) + (f" (+{len(cfg.get('location_variants', []))-3})" if len(cfg.get("location_variants", [])) > 3 else "")),
            ("Offset ceny:", f"+{cfg.get('price_offset', 0)} PLN"),
        ]
        for label, value in details:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=1)
            ctk.CTkLabel(row, text=label, width=120, anchor="w", font=ctk.CTkFont(size=11), text_color=("#6b7280", "#9ca3af")).pack(side="left")
            ctk.CTkLabel(row, text=value, anchor="w", font=ctk.CTkFont(size=11)).pack(side="left")
        # bottom padding
        ctk.CTkLabel(card, text="", height=1).pack(pady=(0, 4))
