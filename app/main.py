"""Entry point aplikacji Marketia OLX Poster.

Uruchomienie:
    python -m app.main

Obowiązki:
  1. Setup loggera (plik + console).
  2. Ensure output dirs.
  3. Run DB migrations (idempotentne).
  4. Uruchom GUI. Try/except łapie wszystko → messagebox + log.
"""
from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler

from . import config
from .data.shared_db import run_migrations


def _setup_logging() -> None:
    config.ensure_dirs()
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(
                config.LOGS_DIR / "app.log",
                maxBytes=5_000_000,
                backupCount=5,
                encoding="utf-8",
            ),
        ],
    )


class App:
    """Cienki wrapper — trzyma referencję do MainWindow.

    Powód: smoke test importuje ``App`` bez wchodzenia w mainloop.
    """

    def __init__(self) -> None:
        # Lazy import — smoke test importuje App bez tkinter dostępności.
        from .gui.main_window import MainWindow
        self.window = MainWindow()

    def run(self) -> None:
        self.window.mainloop()


def _ensure_consent(log: logging.Logger) -> bool:
    """Pokaż first-run consent modal jeśli brak lub outdated.

    Zwraca True gdy można uruchomić GUI. False = user odmówił → main() exit(0).
    """
    from .gui.first_run import has_consent, show_consent_modal

    if has_consent():
        return True

    log.warning("Brak consent.json — pokazuję first-run modal")
    accepted = show_consent_modal()
    if not accepted:
        log.warning("User odmówił zgody — kończę aplikację")
        return False
    log.info("Consent zaakceptowany")
    return True


def main() -> int:
    _setup_logging()
    log = logging.getLogger("marketia.main")
    try:
        applied = run_migrations()
        if applied:
            log.info("migrations applied: %s", applied)
        else:
            log.info("migrations: nothing to apply")

        if not _ensure_consent(log):
            return 0

        app = App()
        app.run()
        return 0
    except Exception as exc:
        log.exception("fatal error: %s", exc)
        # macOS: pokaż messagebox jeśli tkinter dostępny.
        try:
            import tkinter.messagebox as mb
            mb.showerror(
                "Marketia OLX Poster — fatal error",
                f"{exc}\n\n{traceback.format_exc(limit=6)}",
            )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
