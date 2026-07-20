"""Główne okno aplikacji.

Layout:
  - Header: tytuł + STOP ALL (KillSwitchButton) po prawej
  - Sidebar: Produkty / Konta / Miasta / Kolejka / Logi / Ustawienia
    (Faza 1 aktywna tylko "Produkty")
  - Main panel: aktualnie wybrana zakładka
  - Status bar footer: konta / kolejka / ostatnie

Threading skeleton (learning: Tkinter thread safety):
  - Worker (Faza 2+) NIGDY nie wywołuje widget ops. Tylko `self.q.put(msg)`.
  - Main poller `_poll_queue`:
      * OUTER try/except catch-all + finally z self.after(100, self._poll_queue)
        → poller NIE UMIERA nawet gdy handler eksploduje
      * INNER try/except per-message → jeden zły msg nie zabija drainera
      * handle_msg dispatch po tagu
  - Test bogus tag przy init → weryfikuje że poller drainuje ("__test_unknown_tag__")
"""
from __future__ import annotations

import logging
import queue
from typing import Any, Callable

import customtkinter as ctk

from .. import config
from .kill_switch_button import KillSwitchButton
from .product_selector import ProductSelector
from .queue_view import QueueView

__all__ = ["MainWindow"]

_LOG = logging.getLogger("marketia.gui.main_window")

#: (label, active, icon_emoji) — kolejność = workflow: wczytaj → skonfiguruj → wystaw → monitoruj
_SIDEBAR_ITEMS = [
    ("Produkty",   True, "📦"),
    ("Konta",      True, "👥"),
    ("Miasta",     True, "🏙"),
    ("Kolejka",    True, "📋"),
    ("Logi",       True, "📊"),
    ("Ustawienia", True, "⚙"),
]

#: Marketia brand color (spójne z icon.icns squircle).
_ACCENT = "#dc2626"
_ACCENT_HOVER = "#b91c1c"


class MainWindow(ctk.CTk):
    """CTk root window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Marketia OLX Poster")
        self.geometry("1240x820")
        self.minsize(1080, 680)

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("dark-blue")

        # Icon w oknie + Dock (jeśli asset istnieje).
        self._apply_icon()

        # Queue skeleton (learning: worker MUSI używać tylko q.put)
        self.q: queue.Queue[tuple[Any, ...]] = queue.Queue()

        # Heartbeat state — pełna implementacja workera w Fazie 4.
        self._worker_heartbeat: int = 0
        self._last_status_ts_ms: int = 0

        self._active_tab: str = "Produkty"
        self._tab_buttons: dict[str, ctk.CTkButton] = {}
        self._main_panel_current: ctk.CTkBaseClass | None = None

        self._build_layout()

        # Chaos test: bogus tag przy init, poller MUSI drainować bez śmierci.
        self.q.put(("__test_unknown_tag__",))

        # Start poll loop
        self.after(100, self._poll_queue)

    # =============================================================== Layout

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header row 0
        self._build_header()

        # Sidebar row 1 col 0
        self._build_sidebar()

        # Main panel row 1 col 1
        self._main_panel = ctk.CTkFrame(self, corner_radius=0)
        self._main_panel.grid(row=1, column=1, sticky="nsew")
        self._main_panel.grid_columnconfigure(0, weight=1)
        self._main_panel.grid_rowconfigure(0, weight=1)

        # Status bar row 2 cols 0-1
        self._build_status_bar()

        # Aktywna zakładka Produkty
        self._activate_tab("Produkty")

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, corner_radius=0, height=48)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Marketia OLX Poster",
            font=ctk.CTkFont(size=17, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=8)

        # Pomoc: kategorie PJS (ściąga)
        ctk.CTkButton(
            header,
            text="❓  Kategorie PJS",
            fg_color="transparent",
            hover_color=("#e5e7eb", "#374151"),
            text_color=("#111827", "#e5e7eb"),
            width=140,
            height=32,
            command=self._on_pjs_help,
        ).grid(row=0, column=1, sticky="e", padx=8, pady=6)

        # Kill switch — grid (spójny z resztą header) zamiast pack.
        KillSwitchButton(header, on_activate=self._on_kill_switch).grid(
            row=0, column=2, sticky="e", padx=12, pady=6
        )

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, width=200, corner_radius=0, fg_color=("#f9fafb", "#111827"))
        sidebar.grid(row=1, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        # Workflow label na górze sidebar
        ctk.CTkLabel(
            sidebar,
            text="  WORKFLOW",
            anchor="w",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("#6b7280", "#9ca3af"),
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(16, 4))

        for i, (label, active, emoji) in enumerate(_SIDEBAR_ITEMS, start=1):
            btn = ctk.CTkButton(
                sidebar,
                text=f"  {emoji}  {label}",
                anchor="w",
                fg_color="transparent",
                text_color=("#111827", "#e5e7eb"),
                hover_color=("#e5e7eb", "#374151"),
                corner_radius=8,
                height=36,
                font=ctk.CTkFont(size=13),
                state="normal" if active else "disabled",
                command=(lambda name=label: self._activate_tab(name)) if active else None,
            )
            btn.grid(row=i, column=0, sticky="ew", padx=8, pady=2)
            self._tab_buttons[label] = btn

        # Footer sidebar: wersja
        ctk.CTkLabel(
            sidebar,
            text="v1.0 · dropshipping",
            anchor="w",
            font=ctk.CTkFont(size=9),
            text_color=("#9ca3af", "#6b7280"),
        ).grid(row=99, column=0, sticky="sew", padx=12, pady=12)
        sidebar.grid_rowconfigure(99, weight=1)

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self, corner_radius=0, height=30, fg_color=("#f3f4f6", "#111827"))
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)

        self._status_var = ctk.StringVar(
            value="🟢 System OK · Konta: 0 · Kolejka: 0 · Ostatnia aktywność: —"
        )
        ctk.CTkLabel(
            bar,
            textvariable=self._status_var,
            anchor="w",
            font=ctk.CTkFont(size=11),
            text_color=("#374151", "#d1d5db"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=6)

    # ================================================= Icon (window + Dock)

    def _apply_icon(self) -> None:
        """Ustaw ikonę okna. Best-effort — nie failuje gdy asset brak."""
        try:
            from pathlib import Path
            from tkinter import PhotoImage
            icon_path = Path(__file__).resolve().parent.parent.parent / "data" / "marketia_icon_128.png"
            if icon_path.is_file():
                self._icon_photo = PhotoImage(file=str(icon_path))
                self.iconphoto(True, self._icon_photo)
        except Exception:
            _LOG.debug("iconphoto failed — skipping", exc_info=True)

    # =========================================================== Tab switch

    def _activate_tab(self, name: str) -> None:
        self._active_tab = name
        if self._main_panel_current is not None:
            self._main_panel_current.destroy()
            self._main_panel_current = None

        if name == "Produkty":
            panel = ProductSelector(self._main_panel)
        elif name == "Kolejka":
            panel = QueueView(self._main_panel, main_window=self)
        elif name == "Konta":
            from .account_panel import AccountPanel
            panel = AccountPanel(self._main_panel)
        elif name == "Miasta":
            from .city_config import CityConfig
            panel = CityConfig(self._main_panel)
        elif name == "Logi":
            from .logs_view import LogsView
            panel = LogsView(self._main_panel)
        elif name == "Ustawienia":
            from .settings import Settings
            panel = Settings(self._main_panel)
        else:
            panel = ctk.CTkLabel(
                self._main_panel,
                text=f"Zakładka '{name}' — nieznana.",
                anchor="center",
            )
        panel.grid(row=0, column=0, sticky="nsew")
        self._main_panel_current = panel

    # ================================================= Handler registry API

    def register_handler(self, tag: str, handler: Callable[..., None]) -> None:
        """Rejestruje handler dla message tag'a.

        Używane przez QueueView (queue_update), ban_detector (ban_signal),
        itd. Handler jest wołany BEZ ``self`` — otrzymuje tylko args z msg.
        """
        # Wrap: dispatch dla handle_msg oczekuje sygnatury ``fn(self, *args)``
        # dlatego zapisujemy pod bound-style adapter.
        def _adapter(_self, *args, **kwargs):
            handler(*args, **kwargs)

        _MSG_HANDLERS[tag] = _adapter

    # =========================================================== Threading

    def _poll_queue(self) -> None:
        """Drainer kolejki — 3-warstwowy try/except zgodnie z learning.

        WARSTWA 1 (OUTER): catch-all + finally: reschedule. Poller NIGDY nie umiera.
        WARSTWA 2 (INNER): per-message try/except. Zły msg nie łamie całego drenu.
        WARSTWA 3: handle_msg dispatch po tagu (loguje nieznane).
        """
        try:
            drained = 0
            while drained < 64:  # cap na iterację — nie blokuj GUI
                try:
                    msg = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle_msg(msg)
                except Exception:
                    _LOG.exception("handler failed on msg=%r", msg)
                finally:
                    drained += 1
        except Exception:
            _LOG.exception("poller outer failure (bardzo źle — sprawdź logi)")
        finally:
            # Reschedule ZAWSZE — nawet gdy outer wywalił się.
            self.after(100, self._poll_queue)

    def _handle_msg(self, msg: tuple[Any, ...]) -> None:
        """Dispatch po tagu. Nieznane tagi tylko logowane (nie failują)."""
        if not msg:
            _LOG.debug("empty msg ignored")
            return
        tag = msg[0]
        handler: Callable[..., None] | None = _MSG_HANDLERS.get(tag)
        if handler is None:
            _LOG.debug("unknown tag ignored: %r", tag)
            return
        handler(self, *msg[1:])

    # ============================================================ Handlers

    def _on_status(self, text: str) -> None:
        self._status_var.set(text)

    def _on_heartbeat(self, worker_counter: int) -> None:
        # Rate limit statusu do 1× / 2 s (learning: nie zalewaj GUI).
        import time
        now_ms = int(time.monotonic() * 1000)
        self._worker_heartbeat = int(worker_counter)
        if now_ms - self._last_status_ts_ms >= 2000:
            self._last_status_ts_ms = now_ms
            # W Fazie 1 status bar dostaje generyczny placeholder.
            self._status_var.set(
                f"Konta: 0 | Kolejka: 0 | Ostatnie: heartbeat #{self._worker_heartbeat}"
            )

    def _on_error(self, message: str) -> None:
        _LOG.error("worker error: %s", message)

    def _on_kill_switch(self) -> None:
        from ..monitor.kill_switch import kill_switch_activate
        import tkinter.messagebox as mb
        try:
            result = kill_switch_activate(reason="gui_button_pressed")
        except Exception:
            _LOG.exception("kill_switch_activate failed")
            mb.showerror("STOP ALL", "Kill switch failed — sprawdź logi.")
            return
        mb.showinfo(
            "STOP ALL activated",
            f"Anulowano {result['canceled_jobs']} zadań.\n"
            f"Spauzowano {result['paused_accounts']} kont.\n\n"
            "Aby wznowić: odblokuj każde konto ręcznie w tabie Konta.",
        )

    def _on_pjs_help(self) -> None:
        """Otwiera modal ze ściągą kategorii OLX obsługujących PJS."""
        try:
            from .pjs_cheatsheet import show_pjs_cheatsheet
            show_pjs_cheatsheet(self)
        except Exception:
            _LOG.exception("show_pjs_cheatsheet failed")

    def _on_pjs_missing(self, job_id: int, sku: str, category_hint: str) -> None:
        """Handler dla event `("pjs_missing", job_id, sku, category)` z workera.

        Otwiera PjsDecisionModal z 3 opcjami: skip_pjs_retry / cancel / decide_later.
        """
        try:
            from .pjs_decision_modal import PjsDecisionModal
            PjsDecisionModal(
                self,
                job_id=int(job_id),
                sku=str(sku),
                category_hint=str(category_hint),
                on_decision=self._handle_pjs_decision,
            )
        except Exception:
            _LOG.exception("PjsDecisionModal failed for job %s", job_id)

    def _handle_pjs_decision(self, decision: str, job_id: int) -> None:
        """Apply user's PJS decision (persist do olx_jobs)."""
        from ..data.shared_db import get_connection
        from ..queue.state_machine import JobStatus
        try:
            if decision == "skip_pjs_retry":
                # Odznacz PAUSED → PENDING + last_error='skip_pjs' (worker parse).
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE olx_jobs SET status = ?, last_error = 'skip_pjs' WHERE id = ?",
                        (JobStatus.PENDING.value, job_id),
                    )
                _LOG.info("PJS decision: job %d → PENDING with skip_pjs flag", job_id)
            elif decision == "cancel":
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE olx_jobs SET status = ?, last_error = 'pjs_declined_by_user' WHERE id = ?",
                        (JobStatus.CANCELED.value, job_id),
                    )
                _LOG.info("PJS decision: job %d → CANCELED", job_id)
            elif decision == "decide_later":
                _LOG.info("PJS decision: job %d stays PAUSED (decide later)", job_id)
        except Exception:
            _LOG.exception("_handle_pjs_decision failed for job %s", job_id)


# --- msg handlers registry (moduły workerów w Fazie 2+ mogą dodawać własne) --

_MSG_HANDLERS: dict[Any, Callable[..., None]] = {
    "status": MainWindow._on_status,
    "heartbeat": MainWindow._on_heartbeat,
    "error": MainWindow._on_error,
    "pjs_missing": MainWindow._on_pjs_missing,
}
