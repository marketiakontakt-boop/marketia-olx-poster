"""Kill Switch — reusable czerwony przycisk STOP ALL.

Faza 1: tylko widget + minimalny callback (log + messagebox). Pełna
implementacja (pauza kont, anulacja jobs, graceful browser stop) w Fazie 4.
"""
from __future__ import annotations

import logging
import tkinter.messagebox as messagebox
from typing import Callable

import customtkinter as ctk

__all__ = ["KillSwitchButton"]

_LOG = logging.getLogger("marketia.gui.kill_switch")


class KillSwitchButton(ctk.CTkButton):
    """Czerwony STOP ALL widoczny stale w headerze.

    Args:
        master: parent widget.
        on_activate: opcjonalny callback (Faza 4: wpięcie do orchestratora).
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        on_activate: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        self._on_activate = on_activate
        super().__init__(
            master,
            text="🔴 STOP ALL",
            fg_color="#dc2626",
            hover_color="#b91c1c",
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold"),
            width=120,
            height=32,
            command=self._activate,
            **kwargs,
        )

    def _activate(self) -> None:
        _LOG.warning("kill_switch_activated")
        try:
            if self._on_activate is not None:
                self._on_activate()
        finally:
            messagebox.showwarning(
                "STOP ALL",
                "Kill switch aktywowany.\n\n"
                "Faza 1: stub — pełna pauza kont, anulacja kolejki i graceful "
                "browser stop dostarczone w Fazie 4.",
            )
