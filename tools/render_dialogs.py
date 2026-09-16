"""Render the dialogs and the first-run empty states.

    python tools/render_dialogs.py OUTPUT_DIR
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QEventLoop, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from expman.app import MainWindow  # noqa: E402
from expman.db import Database  # noqa: E402
from expman.dialogs import (  # noqa: E402
    CategoryManagerDialog,
    ContributionDialog,
    ExpenseDialog,
    GoalDialog,
    SubscriptionDialog,
)
from expman.import_dialog import ImportDialog  # noqa: E402
from expman.theme import palette, prepare_assets, stylesheet  # noqa: E402

SAMPLE_CSV = [
    "Trans. Date,Post Date,Description,Amount,Category",
    '01/15/2026,01/16/2026,"AMAZON.COM*XY12ABC",25.99,Merchandise',
    '01/16/2026,01/17/2026,"STARBUCKS #1234",5.45,Restaurants',
    '01/18/2026,01/19/2026,"WHOLE FOODS MKT",64.12,Supermarkets',
    '01/20/2026,01/21/2026,"DIRECTPAY FULL BALANCE",-450.00,Payments and Credits',
    '01/22/2026,01/23/2026,"SHELL OIL 12345678",42.10,Gasoline',
    '01/24/2026,01/25/2026,"UNITED AIRLINES",318.40,Travel',
    '01/25/2026,01/26/2026,"KROGER #445",103.87,Supermarkets',
    '01/26/2026,01/27/2026,"RETURN - TARGET",-19.99,Merchandise',
]

PAGES = ["overview", "expenses", "income", "subscriptions", "goals"]


def settle(times: int = 6) -> None:
    for _ in range(times):
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 60)


def shoot(widget, path: str) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.show()
    settle()
    widget.grab().save(path)
    print("wrote", path)


def write_sample(path: str) -> str:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        for line in SAMPLE_CSV:
            print(line, file=handle)
    return path


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out, exist_ok=True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    workdir = tempfile.mkdtemp(prefix="expman_empty_")
    db = Database(os.path.join(workdir, "empty.db"))
    sample_csv = write_sample(os.path.join(workdir, "discover.csv"))

    # A couple of categories carrying data, so the manager has something to show.
    db.add_expense("2026-01-04", 4200, "Groceries", "Weekly shop")
    db.add_expense("2026-01-06", 1850, "Dining", "Lunch")

    # A full goal and a hungry one, so the dialogs below have a spill to explain.
    full_goal = db.add_goal("New headphones", 20000, allocation_pct=10)
    db.add_goal("Emergency fund", 500000, allocation_pct=25)
    db.add_contribution(full_goal, "2026-01-07", 20000, "Saved up")

    for theme in ("dark", "light"):
        pal = palette(theme)
        app.setStyleSheet(stylesheet(pal, prepare_assets(pal, os.path.join(out, "assets"))))

        expense = ExpenseDialog(db.categories(), db.currency)
        expense.resize(440, expense.sizeHint().height())
        shoot(expense, os.path.join(out, f"dialog_expense_{theme}.png"))

        sub = SubscriptionDialog(db.categories(), db.currency)
        sub.amount_field.setText("15.99")
        sub.resize(480, sub.sizeHint().height())
        shoot(sub, os.path.join(out, f"dialog_subscription_{theme}.png"))

        cats = CategoryManagerDialog(db)
        shoot(cats, os.path.join(out, f"dialog_categories_{theme}.png"))

        importer = ImportDialog(db, pal)
        importer.load_path(sample_csv)
        shoot(importer, os.path.join(out, f"dialog_import_{theme}.png"))

        # Editing a goal that has something in it: the reset button is only
        # offered here, and is shown armed so the warning line is in the shot.
        goal = db.get_goal(full_goal)
        editor = GoalDialog(
            db.currency,
            goal=goal,
            typical_income=180000,
            other_pct=25.0,
            reset_plan=db.redistribution_plan(full_goal),
        )
        editor.reset = True
        editor.reset_redistribute = True
        editor._show_reset_state()
        editor.resize(460, editor.sizeHint().height())
        shoot(editor, os.path.join(out, f"dialog_goal_{theme}.png"))

        # More than the goal can hold, so the hint has to say where the rest goes.
        contribution = ContributionDialog(
            goal["name"],
            db.currency,
            plan=lambda cents: db.contribution_plan(full_goal, cents),
        )
        contribution.amount_field.setText("120.00")
        contribution.resize(440, contribution.sizeHint().height())
        shoot(contribution, os.path.join(out, f"dialog_contribution_{theme}.png"))

    # First run: a brand-new database with nothing in it at all.
    fresh = os.path.join(tempfile.mkdtemp(prefix="expman_fresh_"), "fresh.db")
    window = MainWindow(Database(fresh))
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.resize(1280, 820)
    window.show()
    settle()
    for index, name in enumerate(PAGES):
        window.nav_buttons.button(index).setChecked(True)
        window._navigate(index)
        settle()
        target = os.path.join(out, f"empty_{name}.png")
        window.grab().save(target)
        print("wrote", target)

    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
