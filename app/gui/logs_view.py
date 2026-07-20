"""Logs View — tab "Logi".

Tail ostatnich 100 wpisów z `output/logs/audit.jsonl` (PII redakcja
w audit_logger, więc bezpiecznie wyświetlać). Filter po typie eventu.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import customtkinter as ctk

from ..config import LOGS_DIR

__all__ = ["LogsView"]

_LOG = logging.getLogger("marketia.gui.logs_view")

_AUDIT_FILE = Path(LOGS_DIR) / "audit.jsonl"
_MAX_LINES = 100


class LogsView(ctk.CTkFrame):
    """Tab Logi — tail audit.jsonl z filtrem."""

    def __init__(self, parent: ctk.CTkBaseClass):
        super().__init__(parent)
        self._filter_type: str = "Wszystkie"
        self._auto_refresh: bool = False
        self._build()
        self._refresh()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header row: filter + refresh
        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ctk.CTkLabel(header, text="Logi (audit.jsonl)", font=ctk.CTkFont(size=15, weight="bold")).pack(side="left", padx=8)

        self._filter_var = ctk.StringVar(value="Wszystkie")
        ctk.CTkOptionMenu(
            header,
            variable=self._filter_var,
            values=["Wszystkie", "listing_success", "listing_fail", "ban_action", "kill_switch_activated", "kill_switch_deactivated"],
            command=self._on_filter_change,
        ).pack(side="left", padx=4)

        ctk.CTkButton(header, text="Odśwież", width=80, command=self._refresh).pack(side="left", padx=4)

        self._auto_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(header, text="Auto (30s)", variable=self._auto_var, command=self._toggle_auto).pack(side="left", padx=4)

        self._list_frame = ctk.CTkScrollableFrame(self)
        self._list_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def _on_filter_change(self, value: str):
        # Learning: filter state reset po każdej zmianie
        self._filter_type = value
        self._refresh()

    def _toggle_auto(self):
        self._auto_refresh = self._auto_var.get()
        if self._auto_refresh:
            self._schedule_next_refresh()

    def _schedule_next_refresh(self):
        if self._auto_refresh:
            self.after(30_000, lambda: (self._refresh(), self._schedule_next_refresh()))

    def _refresh(self):
        for child in self._list_frame.winfo_children():
            child.destroy()
        self.after(0, lambda: self._list_frame._parent_canvas.yview_moveto(0))

        if not _AUDIT_FILE.is_file():
            ctk.CTkLabel(self._list_frame, text="Brak logów. audit.jsonl nie istnieje.").pack(pady=20)
            return

        try:
            lines = _AUDIT_FILE.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            _LOG.error("Failed to read audit.jsonl: %s", exc)
            ctk.CTkLabel(self._list_frame, text=f"Błąd odczytu: {exc}").pack(pady=20)
            return

        # Tail ostatnich N + filter
        entries = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if self._filter_type != "Wszystkie" and entry.get("type") != self._filter_type:
                continue
            entries.append(entry)
            if len(entries) >= _MAX_LINES:
                break

        if not entries:
            ctk.CTkLabel(self._list_frame, text=f"Brak wpisów dla filtra: {self._filter_type}").pack(pady=20)
            return

        for entry in entries:
            self._render_entry(entry)

    def _render_entry(self, entry: dict):
        ts = entry.get("ts", "")
        try:
            ts_short = datetime.fromisoformat(ts).strftime("%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            ts_short = ts[:16]
        typ = entry.get("type", "?")
        summary = " | ".join(
            f"{k}={v}" for k, v in entry.items()
            if k not in ("ts", "type") and not isinstance(v, (dict, list))
        )[:200]

        row = ctk.CTkFrame(self._list_frame, corner_radius=4, fg_color=("#f3f4f6", "#1f2937"))
        row.pack(fill="x", padx=2, pady=1)
        ctk.CTkLabel(row, text=ts_short, width=110, anchor="w", font=ctk.CTkFont(size=10, family="Menlo"), text_color=("#6b7280", "#9ca3af")).pack(side="left", padx=(6, 4))
        ctk.CTkLabel(row, text=typ, width=140, anchor="w", font=ctk.CTkFont(size=10, weight="bold")).pack(side="left", padx=4)
        ctk.CTkLabel(row, text=summary, anchor="w", font=ctk.CTkFont(size=10)).pack(side="left", padx=4, fill="x", expand=True)
