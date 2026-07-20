"""py2app setup dla Marketia OLX Poster.

Uruchamiane przez ``build.sh``. Bezpośrednio:
    python setup.py py2app --arch universal2

Wymaga: ``py2app`` w venv (nie w requirements.txt bo tylko dev build).
Instalacja: ``pip install py2app``.
"""
from setuptools import setup

APP = ["app/main.py"]

DATA_FILES = [
    ("data", ["data/city_templates.json"]),
    ("", ["DISCLAIMER.md", "README.md"]),
]

OPTIONS = {
    "iconfile": "icon.icns",
    "plist": {
        "CFBundleName": "Marketia OLX Poster",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "CFBundleIdentifier": "com.marketia.olxposter",
        "CFBundleExecutable": "main",
        "CFBundleDisplayName": "Marketia OLX Poster",
        "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.business",
        # TCC pre-authorizations (macOS pyta przy pierwszym uruchomieniu).
        "NSDocumentsFolderUsageDescription": (
            "Aplikacja zapisuje logi i konfigurację w Documents."
        ),
        "NSDesktopFolderUsageDescription": (
            "Możliwe pytania o dostęp do skrótu na biurku."
        ),
    },
    "packages": [
        "customtkinter",
        "playwright",
        "cryptography",
        "keyring",
        "lxml",
        "google",
        "dotenv",
    ],
    "includes": [
        "app",
        "app.data", "app.data.shared_db",
        "app.olx", "app.olx.browser_pool", "app.olx.humanizer",
        "app.olx.listing_creator", "app.olx.selector_registry",
        "app.olx.city_variants", "app.olx.pjs_selector",
        "app.olx.login_manager", "app.olx.vision_fallback",
        "app.queue", "app.queue.state_machine", "app.queue.daily_planner",
        "app.queue.job_scheduler", "app.queue.retry_manager",
        "app.ai",
        "app.security",
        "app.monitor", "app.monitor.ban_detector", "app.monitor.kill_switch",
        "app.monitor.health_check", "app.monitor.audit_logger",
        "app.monitor.notification",
        "app.gui", "app.gui.main_window", "app.gui.first_run",
        "app.gui.product_selector", "app.gui.queue_view",
        "app.gui.account_panel", "app.gui.city_config",
        "app.gui.logs_view", "app.gui.settings",
        "app.gui.kill_switch_button",
    ],
    "excludes": [
        # NIE excludujemy PIL — używamy w scripts/make_icon_png.py, ale
        # aplikacja runtime nie potrzebuje więc excludeujemy z app bundle.
        "PIL", "numpy", "scipy", "matplotlib",
        "tornado", "IPython", "jupyter",
    ],
    "resources": ["data/"],
    "strip": True,
    "optimize": 2,
}

setup(
    app=APP,
    name="Marketia OLX Poster",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
