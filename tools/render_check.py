"""Render every page offscreen to PNG so the layout can be eyeballed without a display.

    python tools/render_check.py OUTPUT_DIR
"""
from __future__ import annotations

import os
import sys

# The offscreen QPA plugin ships no font database, so text renders as tofu. Use
# the native platform instead and keep the window off the screen with
# WA_DontShowOnScreen -- real fonts, still headless.
if "--offscreen" in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QEventLoop, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from expman.app import MainWindow  # noqa: E402
from expman.db import Database  # noqa: E402
from tools.seed_demo import build_demo_db  # noqa: E402


def settle(times: int = 6) -> None:
    for _ in range(times):
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 60)


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)

    db_path = build_demo_db()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow(Database(db_path))
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(1280, 820)
    window.show()
    settle()

    pages = ["overview", "expenses", "income", "subscriptions", "goals"]
    for theme in ("dark", "light"):
        if window.pal["name"] != theme:
            window._toggle_theme()
            settle()
        for index, name in enumerate(pages):
            window.nav_buttons.button(index).setChecked(True)
            window._navigate(index)
            settle()
            target = os.path.join(out, f"{name}_{theme}.png")
            window.grab().save(target)
            print("wrote", target)

    # Hover state on the middle slice, to prove the donut/legend sync.
    window._toggle_theme()  # back to dark
    window.nav_buttons.button(0).setChecked(True)
    window._navigate(0)
    settle()
    window.overview.donut.set_hover(1)
    window.overview.legend.set_hover(1)
    settle()
    target = os.path.join(out, "overview_hover.png")
    window.grab().save(target)
    print("wrote", target)

    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
