"""Tab Kolejka — timeline + tabela jobs + cascade banner.

Learning:
- CTkScrollableFrame yview_moveto(0) po każdym rebuild tabeli (learning 2026-06-30).
- Filter state reset po każdej operacji (Cancel/Retry) — reset checkboxes + _page=0.
- Zero widget ops z workera — subscription przez ``main_window.q.put(("queue_update",...))``.
"""
from __future__ import annotations

import logging
import sys
import traceback
from datetime import date, datetime
from typing import Any, Callable

import customtkinter as ctk

from ..data.shared_db import get_connection
from ..queue.daily_planner import (
    ACCOUNT_WINDOWS,
    DAILY_CAPS,
    apply_warmup_cap,
    get_window_for_day,
)
from ..queue.state_machine import (
    JobStatus,
    JobTransitionError,
    count_by_status,
    transition_job,
)

__all__ = ["QueueView"]

_LOG = logging.getLogger("marketia.gui.queue_view")


_STATUS_LABELS: list[tuple[JobStatus, str]] = [
    (JobStatus.PENDING, "pending"),
    (JobStatus.RUNNING, "running"),
    (JobStatus.DONE, "done"),
    (JobStatus.FAILED, "failed"),
    (JobStatus.PAUSED, "paused"),
    (JobStatus.CANCELED, "canceled"),
]

_STATUS_EMOJI: dict[str, str] = {
    "pending": "⏳",
    "running": "🔄",
    "done": "✅",
    "failed": "❌",
    "paused": "⏸",
    "canceled": "🚫",
    "scheduled_later": "🕒",
}


class QueueView(ctk.CTkFrame):
    """CTk panel dla tab 'Kolejka'."""

    def __init__(self, master: ctk.CTkBaseClass, main_window=None, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._main_window = main_window
        self._page: int = 0

        # Domyślnie wszystko zaznaczone.
        self._status_filter: dict[JobStatus, ctk.BooleanVar] = {
            st: ctk.BooleanVar(value=True) for st, _ in _STATUS_LABELS
        }
        self._account_filter: dict[str, ctk.BooleanVar] = {
            acc: ctk.BooleanVar(value=True) for acc in ACCOUNT_WINDOWS.keys()
        }
        self._selected_job_ids: set[int] = set()
        self._all_jobs: list[dict[str, Any]] = []

        self._build_layout()

        # Zarejestruj handler dla queue_update.
        if main_window is not None:
            try:
                main_window.register_handler("queue_update", self._on_queue_update)
            except Exception:
                _LOG.debug("main_window.register_handler niedostępny — Faza 3 fallback")

        self.refresh()

    # =============================================================== Layout

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # 1. Header + refresh
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        ctk.CTkLabel(
            header,
            text="Kolejka",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left")
        self._counters_label = ctk.CTkLabel(header, text="—", anchor="e")
        self._counters_label.pack(side="right", padx=(0, 12))
        ctk.CTkButton(header, text="Odśwież", width=90, command=self.refresh).pack(
            side="right", padx=4
        )

        # 2. Timeline
        self._timeline_frame = ctk.CTkFrame(self, fg_color=("#f3f4f6", "#1f2937"))
        self._timeline_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=4)

        # 3. Cascade banner (hidden by default)
        self._cascade_banner = ctk.CTkLabel(
            self,
            text="",
            fg_color=("#fed7aa", "#7c2d12"),
            corner_radius=6,
            height=28,
            anchor="w",
        )
        # Grid tylko gdy jest kaskada.

        # 4. Filters
        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        self._build_filters(filters)

        # 5. Table (scrollable)
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.grid(row=3, column=0, sticky="nsew", padx=12, pady=(4, 4))
        self._scroll.grid_columnconfigure(0, weight=1)

        # 6. Action buttons row
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", padx=12, pady=(4, 12))
        ctk.CTkButton(
            actions, text="Anuluj wybrane", command=self._on_cancel_selected
        ).pack(side="left", padx=4)
        ctk.CTkButton(actions, text="Retry", command=self._on_retry_selected).pack(
            side="left", padx=4
        )
        ctk.CTkButton(
            actions,
            text="Wznów cascade wcześniej",
            command=self._on_resume_cascade,
        ).pack(side="left", padx=4)

    def _build_filters(self, parent: ctk.CTkFrame) -> None:
        # Status filter
        ctk.CTkLabel(parent, text="Status:", font=ctk.CTkFont(size=11, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        col = 1
        for st, label in _STATUS_LABELS:
            ctk.CTkCheckBox(
                parent,
                text=label,
                variable=self._status_filter[st],
                command=self._on_filter_change,
                width=90,
            ).grid(row=0, column=col, sticky="w", padx=4)
            col += 1

        # Account filter
        ctk.CTkLabel(
            parent, text="Konto:", font=ctk.CTkFont(size=11, weight="bold")
        ).grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        col = 1
        for acc in ACCOUNT_WINDOWS.keys():
            short = acc.replace("marketia-", "")
            ctk.CTkCheckBox(
                parent,
                text=short,
                variable=self._account_filter[acc],
                command=self._on_filter_change,
                width=110,
            ).grid(row=1, column=col, sticky="w", padx=4, pady=(4, 0))
            col += 1

    # =============================================================== Data

    def refresh(self) -> None:
        """Reload jobs z DB + rebuild UI. Reset filter state gdy zewnętrzne wywołanie."""
        try:
            counters = count_by_status()
        except Exception:
            traceback.print_exc(file=sys.stdout)
            counters = {}
        self._render_counters(counters)

        try:
            self._all_jobs = self._load_jobs()
        except Exception:
            traceback.print_exc(file=sys.stdout)
            _LOG.exception("load jobs failed")
            self._all_jobs = []

        self._render_timeline()
        self._render_cascade_banner()
        self._rebuild_rows()

    def _load_jobs(self, limit: int = 300) -> list[dict[str, Any]]:
        with get_connection(read_only=True) as conn:
            rows = conn.execute(
                """
                SELECT id, sku, account_name, city, scheduled_at, status, retries, last_error
                FROM olx_jobs
                ORDER BY COALESCE(scheduled_at, created_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _render_counters(self, counters: dict[str, int]) -> None:
        parts = [f"{k}={v}" for k, v in sorted(counters.items())]
        self._counters_label.configure(
            text=" | ".join(parts) if parts else "brak jobs"
        )

    # -------------------------------------------------------- Timeline

    def _render_timeline(self) -> None:
        for child in list(self._timeline_frame.winfo_children()):
            child.destroy()

        today = date.today()
        for i, account in enumerate(ACCOUNT_WINDOWS.keys()):
            try:
                start_dt, end_dt = get_window_for_day(account, today)
            except KeyError:
                continue

            base_cap = DAILY_CAPS.get(account, 0)
            # W Fazie 3 nie znamy warmup_days z GUI — użyjemy base_cap.
            cap = apply_warmup_cap(account, base_cap, 0)

            today_jobs = [
                j
                for j in self._all_jobs
                if j["account_name"] == account and _is_today(j.get("scheduled_at"), today)
            ]
            done = sum(1 for j in today_jobs if j["status"] == "done")
            pending = sum(1 for j in today_jobs if j["status"] == "pending")

            summary = (
                f"{account:20s}  "
                f"slot {start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}  "
                f"| done {done}/{cap}  | pending {pending}"
            )
            ctk.CTkLabel(
                self._timeline_frame,
                text=summary,
                anchor="w",
                font=ctk.CTkFont(size=11, family="Menlo"),
            ).grid(row=i, column=0, sticky="ew", padx=8, pady=2)

    # -------------------------------------------------------- Cascade banner

    def _render_cascade_banner(self) -> None:
        """Pokazuje banner jeśli któreś konto ma pause_reason=cascade."""
        try:
            with get_connection(read_only=True) as conn:
                rows = conn.execute(
                    """
                    SELECT name, pause_reason FROM olx_accounts_meta
                    WHERE is_paused = 1 AND pause_reason LIKE 'cascade%'
                    """
                ).fetchall()
        except Exception:
            rows = []

        if not rows:
            self._cascade_banner.grid_forget()
            return

        names = ", ".join(row["name"] for row in rows)
        self._cascade_banner.configure(
            text=f"CASCADE PAUSE ACTIVE: {names} (kliknij 'Wznów cascade wcześniej')"
        )
        self._cascade_banner.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 4))

    # -------------------------------------------------------- Rows

    def _visible_jobs(self) -> list[dict[str, Any]]:
        allowed_status = {
            st.value for st, var in self._status_filter.items() if var.get()
        }
        allowed_accounts = {
            acc for acc, var in self._account_filter.items() if var.get()
        }
        return [
            j
            for j in self._all_jobs
            if j["status"] in allowed_status and j["account_name"] in allowed_accounts
        ]

    def _rebuild_rows(self) -> None:
        for child in list(self._scroll.winfo_children()):
            child.destroy()

        visible = self._visible_jobs()

        # Header row
        header = ctk.CTkFrame(self._scroll, fg_color=("#e5e7eb", "#111827"))
        header.grid(row=0, column=0, sticky="ew", pady=(0, 2))
        for i, (txt, w) in enumerate(
            [("☐", 0), ("ID", 1), ("SKU", 2), ("Konto", 2), ("Miasto", 2),
             ("Stan", 2), ("Zaplanowane", 3), ("Retries", 1)]
        ):
            header.grid_columnconfigure(i, weight=w)
            ctk.CTkLabel(
                header,
                text=txt,
                font=ctk.CTkFont(size=11, weight="bold"),
                anchor="w",
            ).grid(row=0, column=i, sticky="ew", padx=6, pady=4)

        if not visible:
            ctk.CTkLabel(
                self._scroll,
                text="Brak jobs pasujących do filtrów",
                anchor="center",
                text_color="#9ca3af",
            ).grid(row=1, column=0, sticky="nsew", padx=12, pady=48)
        else:
            for idx, job in enumerate(visible, start=1):
                self._render_row(idx, job)

        # Learning: yview_moveto(0) po każdym rebuild.
        try:
            self._scroll._parent_canvas.yview_moveto(0)
        except Exception:
            _LOG.debug("scroll reset skipped")

    def _render_row(self, idx: int, job: dict[str, Any]) -> None:
        row = ctk.CTkFrame(self._scroll, fg_color=("#f9fafb", "#111827"))
        row.grid(row=idx, column=0, sticky="ew", pady=1)
        for i, w in enumerate((0, 1, 2, 2, 2, 2, 3, 1)):
            row.grid_columnconfigure(i, weight=w)

        job_id = int(job["id"])
        var = ctk.BooleanVar(value=job_id in self._selected_job_ids)

        def _toggle(jid: int = job_id, v: ctk.BooleanVar = var) -> None:
            if v.get():
                self._selected_job_ids.add(jid)
            else:
                self._selected_job_ids.discard(jid)

        status = str(job["status"])
        emoji = _STATUS_EMOJI.get(status, "•")
        sched = _fmt_dt(job.get("scheduled_at"))

        ctk.CTkCheckBox(
            row, text="", variable=var, command=_toggle, width=24
        ).grid(row=0, column=0, padx=6, pady=3)
        ctk.CTkLabel(row, text=str(job_id), anchor="w").grid(row=0, column=1, sticky="ew", padx=6)
        ctk.CTkLabel(row, text=str(job["sku"]), anchor="w").grid(row=0, column=2, sticky="ew", padx=6)
        ctk.CTkLabel(
            row, text=str(job["account_name"]).replace("marketia-", ""), anchor="w"
        ).grid(row=0, column=3, sticky="ew", padx=6)
        ctk.CTkLabel(row, text=str(job["city"]), anchor="w").grid(row=0, column=4, sticky="ew", padx=6)
        ctk.CTkLabel(row, text=f"{emoji} {status}", anchor="w").grid(row=0, column=5, sticky="ew", padx=6)
        ctk.CTkLabel(row, text=sched, anchor="w").grid(row=0, column=6, sticky="ew", padx=6)
        ctk.CTkLabel(row, text=str(job.get("retries") or 0), anchor="e").grid(
            row=0, column=7, sticky="ew", padx=6
        )

    # =============================================================== Actions

    def _on_filter_change(self) -> None:
        # Learning: filter change → _page=0, ale NIE reset checkboxów (user je sam ustawił).
        self._page = 0
        self._selected_job_ids.clear()
        self._rebuild_rows()

    def _on_cancel_selected(self) -> None:
        self._bulk_transition(JobStatus.CANCELED, reason="user_cancel")

    def _on_retry_selected(self) -> None:
        # FAILED → PENDING lub CANCELED → (nie dozwolone). Filtrujemy stan przed.
        applied = 0
        for jid in list(self._selected_job_ids):
            job = self._find_job(jid)
            if job is None:
                continue
            try:
                current = JobStatus(job["status"])
                if current not in {JobStatus.FAILED}:
                    continue
                transition_job(jid, current, JobStatus.PENDING, reason="user_retry")
                applied += 1
            except (JobTransitionError, ValueError):
                traceback.print_exc(file=sys.stdout)
        _LOG.info("retry applied to %d jobs", applied)
        self._reset_after_bulk_op()

    def _on_resume_cascade(self) -> None:
        """Wznawia wszystkie konta w cascade pause (user decision, own risk)."""
        try:
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE olx_accounts_meta
                    SET is_paused = 0, pause_reason = NULL
                    WHERE pause_reason LIKE 'cascade%'
                    """
                )
                # Wznów też same jobs oznaczone jako paused (cascade).
                conn.execute(
                    """
                    UPDATE olx_jobs
                    SET status = ?, last_error = NULL
                    WHERE status = ? AND last_error LIKE 'cascade%'
                    """,
                    (JobStatus.PENDING.value, JobStatus.PAUSED.value),
                )
        except Exception:
            traceback.print_exc(file=sys.stdout)
            _LOG.exception("resume cascade failed")
        self._reset_after_bulk_op()

    def _bulk_transition(self, target: JobStatus, reason: str = "") -> None:
        applied = 0
        for jid in list(self._selected_job_ids):
            job = self._find_job(jid)
            if job is None:
                continue
            try:
                current = JobStatus(job["status"])
                transition_job(jid, current, target, reason=reason)
                applied += 1
            except (JobTransitionError, ValueError):
                traceback.print_exc(file=sys.stdout)
        _LOG.info("bulk transition to %s: %d jobs", target.value, applied)
        self._reset_after_bulk_op()

    def _reset_after_bulk_op(self) -> None:
        """Learning: filter state reset po każdej operacji zmieniającej statusy.

        Reset checkboxes → True (wszystko widoczne), _page=0, selected clear.
        """
        for var in self._status_filter.values():
            var.set(True)
        for var in self._account_filter.values():
            var.set(True)
        self._page = 0
        self._selected_job_ids.clear()
        self.refresh()

    def _find_job(self, job_id: int) -> dict[str, Any] | None:
        for j in self._all_jobs:
            if int(j["id"]) == job_id:
                return j
        return None

    # =============================================================== Queue update

    def _on_queue_update(self, job_id: int, new_status: str) -> None:
        """Handler dla ("queue_update", job_id, new_status) messages z workera.

        Odświeża pojedynczy row (albo cały widok jako fallback).
        """
        # Prosty fallback: full refresh (przy większej liczbie jobs można zoptymalizować).
        self.refresh()


# =============================================================== Helpers

def _fmt_dt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    try:
        # sqlite może zwrócić str
        parsed = datetime.fromisoformat(str(value))
        return parsed.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)[:16]


def _is_today(value: Any, today: date) -> bool:
    if value is None:
        return False
    if isinstance(value, datetime):
        return value.date() == today
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.date() == today
    except Exception:
        return False
