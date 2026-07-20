"""PJS Decision Modal — pyta usera co robić gdy kategoria nie ma PJS.

Wyświetlane przez main_window po odebraniu event ``("pjs_missing", job_id, sku, category_hint)``
z queue workera.

3 opcje:
  1. Wystaw jako NIEOPŁACONE (skip_pjs=True, retry) — user świadomie
  2. Cofnij ogłoszenie (transition → CANCELED z reason)
  3. Zdecyduj później (keep PAUSED — user wróci w GUI Kolejka)
"""
from __future__ import annotations

import logging
from typing import Callable, Literal

import customtkinter as ctk

__all__ = ["PjsDecisionModal", "PjsDecision"]

_LOG = logging.getLogger("marketia.gui.pjs_decision")

PjsDecision = Literal["skip_pjs_retry", "cancel", "decide_later"]


class PjsDecisionModal(ctk.CTkToplevel):
    """Modal z 3 przyciskami. Result przez callback ``on_decision(decision, job_id)``."""

    def __init__(
        self,
        parent: ctk.CTkBaseClass,
        job_id: int,
        sku: str,
        category_hint: str,
        on_decision: Callable[[PjsDecision, int], None],
    ):
        super().__init__(parent)
        self._job_id = job_id
        self._on_decision = on_decision

        self.title("PJS niedostępne — decyzja")
        self.geometry("560x420")
        self.minsize(520, 380)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close_x)

        # Bottom fixed buttons
        bottom = ctk.CTkFrame(self, corner_radius=0)
        bottom.pack(side="bottom", fill="x", padx=16, pady=(0, 16))
        ctk.CTkButton(
            bottom,
            text="↩  Cofnij ogłoszenie",
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=self._cancel_listing,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            bottom,
            text="⏸  Zdecyduj później",
            fg_color="transparent",
            border_width=1,
            text_color=("#111827", "#e5e7eb"),
            command=self._decide_later,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            bottom,
            text="⚠  Wystaw jako nieopłacone",
            fg_color="#f59e0b",
            hover_color="#d97706",
            command=self._skip_pjs_retry,
        ).pack(side="right")

        # Body
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            body,
            text="⚠️  Kategoria bez opcji PJS",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color=("#dc2626", "#f87171"),
        ).pack(anchor="w", pady=(0, 8))

        # Detail box
        detail = ctk.CTkFrame(body, corner_radius=8, fg_color=("#fef2f2", "#450a0a"))
        detail.pack(fill="x", pady=(0, 12))
        self._detail_row(detail, "SKU:", sku)
        self._detail_row(detail, "Job ID:", str(job_id))
        self._detail_row(detail, "Kategoria:", category_hint)

        # Explanation
        ctk.CTkLabel(
            body,
            text=(
                "Kategoria wybrana dla produktu NIE oferuje opcji „Zapłać jeśli sprzedasz\" "
                "na OLX. Ogłoszenie zostało wstrzymane. Co zrobić?"
            ),
            wraplength=520,
            justify="left",
            anchor="w",
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", pady=(0, 12))

        # Options explanations
        self._option_row(
            body,
            "⚠  Wystaw jako nieopłacone",
            "Ogłoszenie zostanie wystawione BEZ PJS. Rachunek za wystawienie płacisz z góry.",
            color=("#f59e0b", "#fbbf24"),
        )
        self._option_row(
            body,
            "↩  Cofnij ogłoszenie",
            "Ogłoszenie zostanie oznaczone jako anulowane. Możesz je usunąć z Kolejki.",
            color=("#dc2626", "#f87171"),
        )
        self._option_row(
            body,
            "⏸  Zdecyduj później",
            "Ogłoszenie zostaje w kolejce jako PAUSED. Wrócisz do niego w tabie Kolejka.",
            color=("#6b7280", "#9ca3af"),
        )

    # =============================================================== Helpers

    def _detail_row(self, parent, key: str, value: str):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(
            row, text=key, width=100, anchor="w",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            row, text=value, anchor="w",
            font=ctk.CTkFont(size=11, family="Menlo"),
        ).pack(side="left")

    def _option_row(self, parent, label: str, desc: str, color):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        ctk.CTkLabel(
            row, text=label, anchor="w",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=color, width=200,
        ).pack(side="left", padx=(0, 8), anchor="n")
        ctk.CTkLabel(
            row, text=desc, wraplength=320, justify="left", anchor="w",
            font=ctk.CTkFont(size=11),
        ).pack(side="left", fill="x", expand=True, anchor="n")

    # =============================================================== Actions

    def _skip_pjs_retry(self):
        _LOG.info("PJS decision: skip_pjs_retry for job %d", self._job_id)
        self._on_decision("skip_pjs_retry", self._job_id)
        self.destroy()

    def _cancel_listing(self):
        _LOG.info("PJS decision: cancel for job %d", self._job_id)
        self._on_decision("cancel", self._job_id)
        self.destroy()

    def _decide_later(self):
        _LOG.info("PJS decision: decide_later for job %d", self._job_id)
        self._on_decision("decide_later", self._job_id)
        self.destroy()

    def _on_close_x(self):
        # Zamknięcie X = "decide later" (nie wymuszaj decyzji)
        self._decide_later()
