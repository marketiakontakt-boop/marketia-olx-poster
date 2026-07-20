"""Tab Produkty — CTkScrollableFrame z listą produktów z shared DB.

Faza 1: read-only listing. Filtry, checkboxy, dodanie do kolejki → Faza 3.
"""
from __future__ import annotations

import logging
from typing import Any

import customtkinter as ctk

from ..data import load_from_shared_db

__all__ = ["ProductSelector"]

_LOG = logging.getLogger("marketia.gui.product_selector")


class ProductSelector(ctk.CTkFrame):
    """Panel produktów (Faza 1: kolumny ☐ | SKU | Nazwa | Cena)."""

    def __init__(self, master: ctk.CTkBaseClass, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._products: list[dict[str, Any]] = []
        self._selected_skus: set[str] = set()
        # Reset state variable — Faza 3 przy filter zmianie: _page = 0
        self._page: int = 0

        self._build_layout()
        self.refresh()

    # ------------------------------------------------------------------ UI

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        ctk.CTkLabel(
            header,
            text="Produkty (shared DB)",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left")
        self._status_label = ctk.CTkLabel(header, text="—", anchor="e")
        self._status_label.pack(side="right")

        # Kolumnowy nagłówek
        cols_header = ctk.CTkFrame(self, fg_color="#1f2937")
        cols_header.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 4))
        for i, (text, weight) in enumerate(
            [("☐", 0), ("SKU", 2), ("Nazwa", 6), ("Cena", 2)]
        ):
            cols_header.grid_columnconfigure(i, weight=weight)
            ctk.CTkLabel(
                cols_header,
                text=text,
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w",
            ).grid(row=0, column=i, sticky="ew", padx=6, pady=6)

        # Scrollable body
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self._scroll.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------ Data

    def refresh(self) -> None:
        """Reload produktów z shared DB + rebuild tabeli.

        Learning: po każdym rebuildzie CTkScrollableFrame trzeba przewinąć na
        górę przez _parent_canvas.yview_moveto(0). Również: filter state
        reset → _page = 0.
        """
        try:
            self._products = load_from_shared_db(limit=100)
        except Exception as exc:  # pragma: no cover — DB może być pusta
            _LOG.exception("load_from_shared_db failed: %s", exc)
            self._products = []

        # Filter state reset (widget reset != state reset — obie strony!)
        self._page = 0
        self._selected_skus.clear()

        self._rebuild_rows()
        self._status_label.configure(text=f"{len(self._products)} produktów")

        # Scroll do góry po rebuild
        try:
            self._scroll._parent_canvas.yview_moveto(0)
        except Exception:  # pragma: no cover — CTk internals mogą się zmienić
            _LOG.debug("scroll reset skipped")

    def _rebuild_rows(self) -> None:
        # Wyczyść stare widgety
        for child in list(self._scroll.winfo_children()):
            child.destroy()

        if not self._products:
            ctk.CTkLabel(
                self._scroll,
                text=(
                    "Brak produktów w shared DB.\n"
                    "Uruchom Marketia XML Pro i zaimportuj feed hurtowni,\n"
                    "albo wywołaj load_from_xml(...) ręcznie w Fazie 2."
                ),
                anchor="center",
                justify="center",
                text_color="#9ca3af",
            ).grid(row=0, column=0, sticky="nsew", padx=12, pady=48)
            return

        for i, product in enumerate(self._products):
            self._render_row(i, product)

    def _render_row(self, idx: int, product: dict[str, Any]) -> None:
        row = ctk.CTkFrame(self._scroll, fg_color=("#f3f4f6", "#111827"))
        row.grid(row=idx, column=0, sticky="ew", pady=1)
        for i, weight in enumerate((0, 2, 6, 2)):
            row.grid_columnconfigure(i, weight=weight)

        sku = str(product.get("sku") or product.get("id") or "")
        name = str(product.get("name") or product.get("title") or "")
        price = product.get("price") or "-"

        checkbox_var = ctk.BooleanVar(value=False)

        def _on_toggle(sku_val: str = sku, var: ctk.BooleanVar = checkbox_var) -> None:
            if var.get():
                self._selected_skus.add(sku_val)
            else:
                self._selected_skus.discard(sku_val)

        ctk.CTkCheckBox(row, text="", variable=checkbox_var, command=_on_toggle, width=24).grid(
            row=0, column=0, padx=6, pady=4
        )
        ctk.CTkLabel(row, text=sku, anchor="w").grid(row=0, column=1, sticky="ew", padx=6)
        ctk.CTkLabel(row, text=name, anchor="w").grid(row=0, column=2, sticky="ew", padx=6)
        ctk.CTkLabel(row, text=str(price), anchor="e").grid(row=0, column=3, sticky="ew", padx=6)
