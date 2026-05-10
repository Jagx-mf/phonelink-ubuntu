#!/usr/bin/env python3
"""PhoneLink Ubuntu — Contrôle de votre téléphone Android depuis GNOME."""

import sys
import gi

gi.require_version("Gtk", "4.0")
try:
    gi.require_version("Adw", "1")
    HAS_ADW = True
except (ValueError, RuntimeError):
    HAS_ADW = False

from gi.repository import Gtk

if HAS_ADW:
    from gi.repository import Adw

from app.utils.logger import setup_logging, get_logger
from app.ui.main_window import MainWindow

APP_ID = "com.phonelink.ubuntu"
APP_VERSION = "0.1.0"


def on_activate(app: Gtk.Application) -> None:
    # Prevent duplicate windows on second launch
    existing = app.get_active_window()
    if existing:
        existing.present()
        return
    win = MainWindow(application=app)
    win.present()


def main() -> int:
    setup_logging()
    logger = get_logger(__name__)
    logger.info("PhoneLink Ubuntu v%s — démarrage", APP_VERSION)

    if HAS_ADW:
        app = Adw.Application(application_id=APP_ID)
    else:
        app = Gtk.Application(application_id=APP_ID)

    app.connect("activate", on_activate)
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
