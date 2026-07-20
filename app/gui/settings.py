"""Settings — tab "Ustawienia".

Faza 4: sliders dla humanizer delays + PROMPT_VERSION display + kill switch
deactivate (z double-confirm). ENABLE_VISION_FALLBACK i DEV_MODE checkboxy.
"""
from __future__ import annotations

import logging
import tkinter.messagebox as mb

import customtkinter as ctk

from ..config import HUMAN_DELAY_MAX_S, HUMAN_DELAY_MIN_S, PROMPT_VERSION
from ..monitor.kill_switch import is_kill_switch_active, kill_switch_deactivate

__all__ = ["Settings"]

_LOG = logging.getLogger("marketia.gui.settings")


class Settings(ctk.CTkFrame):
    """Tab Ustawienia — sliders + kill switch reset."""

    def __init__(self, parent: ctk.CTkBaseClass):
        super().__init__(parent)
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self, text="Ustawienia", font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        body = ctk.CTkScrollableFrame(self)
        body.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        # HUMAN_DELAY sliders
        self._section(body, "Humanizer delays (sekundy między ogłoszeniami)")
        self._delay_min = self._slider(body, "Min:", 30, 120, HUMAN_DELAY_MIN_S)
        self._delay_max = self._slider(body, "Max:", 120, 300, HUMAN_DELAY_MAX_S)
        ctk.CTkLabel(
            body,
            text="Zmiana wymaga restartu aplikacji (zapis do .env — TODO Faza 5).",
            text_color=("#f59e0b", "#fbbf24"),
            font=ctk.CTkFont(size=10),
        ).pack(anchor="w", padx=8, pady=(0, 12))

        # PROMPT_VERSION display
        self._section(body, "Cache versioning")
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(row, text="PROMPT_VERSION:", width=180, anchor="w").pack(side="left")
        ctk.CTkLabel(
            row,
            text=PROMPT_VERSION,
            font=ctk.CTkFont(family="Menlo", size=11),
            anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            body,
            text="Bump wymaga zmiany w kodzie (app/config.py). Auto-inwalidacja cache przy odczycie.",
            text_color=("#6b7280", "#9ca3af"),
            font=ctk.CTkFont(size=10),
        ).pack(anchor="w", padx=8, pady=(0, 12))

        # Vision fallback checkbox
        self._section(body, "Feature flags")
        self._vision_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            body,
            text="ENABLE_VISION_FALLBACK (Claude API gdy selectors fail)",
            variable=self._vision_var,
        ).pack(anchor="w", padx=8, pady=2)
        self._dev_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            body,
            text="DEV_MODE (verbose logging + dłuższe timeouts)",
            variable=self._dev_var,
        ).pack(anchor="w", padx=8, pady=2)

        # Kill switch reset
        self._section(body, "Kill switch")
        ctk.CTkLabel(
            body,
            text=f"Status: {'🔴 AKTYWNY' if is_kill_switch_active() else '🟢 nieaktywny'}",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=8, pady=4)
        ctk.CTkButton(
            body,
            text="Deaktywuj kill switch",
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=self._deactivate_kill_switch,
        ).pack(anchor="w", padx=8, pady=4)
        ctk.CTkLabel(
            body,
            text="Wznowienie kont wymaga osobnej akcji w tabie Konta.",
            text_color=("#6b7280", "#9ca3af"),
            font=ctk.CTkFont(size=10),
        ).pack(anchor="w", padx=8, pady=(0, 12))

    def _section(self, parent, title: str):
        ctk.CTkLabel(
            parent,
            text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=8, pady=(12, 4))

    def _slider(self, parent, label: str, minv: int, maxv: int, default: int) -> ctk.CTkSlider:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(row, text=label, width=60, anchor="w").pack(side="left")
        value_label = ctk.CTkLabel(row, text=str(default), width=50, anchor="w", font=ctk.CTkFont(family="Menlo", size=11))
        value_label.pack(side="right")
        slider = ctk.CTkSlider(row, from_=minv, to=maxv, command=lambda v: value_label.configure(text=f"{int(v)}s"))
        slider.set(default)
        slider.pack(side="left", fill="x", expand=True, padx=8)
        return slider

    def _deactivate_kill_switch(self):
        if not is_kill_switch_active():
            mb.showinfo("Kill switch", "Kill switch nie jest aktywny.")
            return
        confirm1 = mb.askyesno(
            "Deaktywacja kill switch",
            "Kill switch jest aktywny. Deaktywować?\n\n"
            "UWAGA: konta pozostaną spauzowane — musisz wznowić ręcznie w tabie Konta.",
        )
        if not confirm1:
            return
        confirm2 = mb.askyesno(
            "Potwierdzenie",
            "Ostatnie potwierdzenie: naprawdę deaktywować kill switch?",
        )
        if not confirm2:
            return
        try:
            kill_switch_deactivate(user_confirmed=True)
            mb.showinfo("Kill switch", "Kill switch deaktywowany.\nKonta wciąż spauzowane.")
        except Exception as exc:
            _LOG.exception("kill_switch_deactivate failed")
            mb.showerror("Błąd", str(exc))
