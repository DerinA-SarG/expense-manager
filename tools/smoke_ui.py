"""Drive the real UI handlers with stubbed dialogs.

Rendering proves the pages lay out; this proves the buttons actually work --
add / edit / delete, subscription posting, filters, theme and currency changes.

    python tools/smoke_ui.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QEventLoop, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from expman import dialogs as dialogs_module  # noqa: E402
from expman import updates  # noqa: E402
from expman.app import MainWindow  # noqa: E402
from expman.db import Database  # noqa: E402
from expman.money import format_cents  # noqa: E402
from expman.pages import expenses as expenses_page  # noqa: E402
from expman.pages import subscriptions as subs_page  # noqa: E402

PASS, FAIL = [], []


def settle(ms: int = 450) -> None:
    """Let queued work run -- the search box is debounced, so a keystroke only
    reaches the table after the timer fires."""
    import time

    deadline = time.perf_counter() + ms / 1000
    while time.perf_counter() < deadline:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    mark = "ok  " if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f"  -- {detail}" if detail and not condition else ""))


class StubDialog:
    """Stands in for a modal dialog: reports accepted, returns fixed values."""

    def __init__(self, values):
        self._values = values

    def __call__(self, *args, **kwargs):
        return self

    def exec(self):
        return 1

    def values(self):
        return dict(self._values)


def stub_confirm(monkey_yes: bool = True, checked: bool = False):
    def _exec(self):
        box = self.checkBox()
        if box is not None:
            box.setChecked(checked)
        return (
            QMessageBox.StandardButton.Yes
            if monkey_yes
            else QMessageBox.StandardButton.Cancel
        )

    return _exec


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    db_path = os.path.join(tempfile.mkdtemp(prefix="expman_smoke_"), "smoke.db")
    window = MainWindow(Database(db_path))
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()

    db = window.db
    exp, subs, over = window.expenses, window.subscriptions, window.overview

    # Silence the informational popups.
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.exec = stub_confirm()

    print("\nExpenses")
    dialogs_module.ExpenseDialog = StubDialog(
        {
            "spent_on": date.today(),
            "amount_cents": 4250,
            "category": "Groceries",
            "description": "Weekly shop",
            "notes": "",
        }
    )
    expenses_page.ExpenseDialog = dialogs_module.ExpenseDialog
    exp.add_expense()
    check("add expense inserts a row", len(db.list_expenses()) == 1)
    check("table shows the new row", exp.model.rowCount() == 1)
    check(
        "overview picks it up",
        over.stat_total.value.text() == format_cents(4250, "$"),
        over.stat_total.value.text(),
    )

    # A brand-new category typed into the combo must be created on the fly.
    expenses_page.ExpenseDialog = StubDialog(
        {
            "spent_on": date.today(),
            "amount_cents": 999,
            "category": "Hobby supplies",
            "description": "Yarn",
            "notes": "for the scarf",
        }
    )
    exp.add_expense()
    check("free-typed category is created", "Hobby supplies" in db.categories())
    check("category filter offers it", exp.category_filter.findData("Hobby supplies") > 0)

    exp.table.selectRow(0)
    selected = exp._selected_ids()
    check("row selection resolves an id", len(selected) == 1, str(selected))

    expenses_page.ExpenseDialog = StubDialog(
        {
            "spent_on": date.today(),
            "amount_cents": 5000,
            "category": "Groceries",
            "description": "Edited",
            "notes": "",
        }
    )
    exp.edit_selected()
    edited = db.conn.execute(
        "SELECT * FROM expenses WHERE id = ?", (selected[0],)
    ).fetchone()
    check("edit writes through", edited["amount_cents"] == 5000, str(edited["amount_cents"]))

    print("\nFilters")
    exp.search.setText("Weekly")
    settle()
    check("search narrows the table", exp.model.rowCount() == 1, str(exp.model.rowCount()))
    exp.search.setText("Edited")
    settle()
    check("search finds the edited row", exp.model.rowCount() == 1, str(exp.model.rowCount()))
    exp.search.setText("zzzz-no-match")
    settle()
    check("no match empties the table", exp.model.rowCount() == 0)
    exp.search.setText("")
    settle()
    check("clearing search restores rows", exp.model.rowCount() == 2)

    for index in range(over.period_box.count()):
        over.period_box.setCurrentIndex(index)
        exp.period_filter.setCurrentIndex(index)
    check("every period option renders", True)
    exp.period_filter.setCurrentIndex(exp.period_filter.count() - 1)

    print("\nSubscriptions")
    start = date.today() - timedelta(days=95)
    subs_page.SubscriptionDialog = StubDialog(
        {
            "name": "Netflix",
            "amount_cents": 1599,
            "category": "Subscriptions",
            "cycle": "monthly",
            "start_date": start,
            "next_due": start,
            "active": True,
            "notes": "",
        }
    )
    before = len(db.list_expenses())
    subs.add_subscription()
    posted = len(db.list_expenses()) - before
    check("adding a back-dated subscription posts its charges", posted == 4, f"posted {posted}")
    check("subscription table shows it", subs.table.rowCount() == 1)
    check(
        "next due moved into the future",
        date.fromisoformat(db.list_subscriptions()[0]["next_due"]) > date.today(),
    )
    check("relaunch posts nothing further", db.post_due_subscriptions() == 0)

    exp.refresh()
    sub_rows = [r for r in db.list_expenses() if r["subscription_id"] is not None]
    check("posted charges are attributed", len(sub_rows) == 4)
    check("posted charges carry the name", sub_rows[0]["description"] == "Netflix")

    subs.table.selectRow(0)
    subs.toggle_selected()
    check("pause deactivates", db.list_subscriptions()[0]["active"] == 0)
    check("paused button offers resume", subs.pause_button.text() == "Resume")
    subs.table.selectRow(0)
    subs.toggle_selected()
    check("resume reactivates", db.list_subscriptions()[0]["active"] == 1)

    print("\nDeletes")
    subs.table.selectRow(0)
    QMessageBox.exec = stub_confirm(checked=False)
    subs.delete_selected()
    check("subscription removed", len(db.list_subscriptions()) == 0)
    check(
        "its logged charges survive by default",
        len([r for r in db.list_expenses() if r["description"] == "Netflix"]) == 4,
    )

    exp.refresh()
    exp.table.selectAll()
    count = len(exp._selected_ids())
    QMessageBox.exec = stub_confirm()
    exp.delete_selected()
    check(f"deleting all {count} expenses empties the log", len(db.list_expenses()) == 0)
    over.refresh()
    check("overview falls back to the empty state", over.chart_stack.currentIndex() == 1)

    print("\nChrome")
    start_theme = window.pal["name"]
    window._toggle_theme()
    check("theme toggles", window.pal["name"] != start_theme)
    check("theme persists", db.get_setting("theme") == window.pal["name"])
    window._toggle_theme()

    window._set_currency("€")
    check("currency persists", db.currency == "€")
    check(
        "currency reaches the UI",
        "€" in over.stat_total.value.text(),
        over.stat_total.value.text(),
    )

    for index in range(3):
        window._navigate(index)
    check("all pages navigate", window.stack.currentIndex() == 2)

    print("\nGoals")
    goals = window.goals
    doomed = db.add_goal("Old plan", 100000, allocation_pct=30)
    keeper = db.add_goal("Keeper", 500000, allocation_pct=10)
    db.add_contribution(doomed, date.today(), 6000, "saved up")
    goals.refresh()
    goals._select(doomed)

    QMessageBox.exec = stub_confirm(checked=False)
    total_before = sum(g["saved_cents"] for g in db.goals())
    goals.delete_selected()
    check("a goal deletes", db.get_goal(doomed) is None)
    check(
        "and without the box its money goes with it",
        sum(g["saved_cents"] for g in db.goals()) == total_before - 6000,
        str([(g["name"], g["saved_cents"]) for g in db.goals()]),
    )

    doomed = db.add_goal("Second thoughts", 100000, allocation_pct=30)
    db.add_contribution(doomed, date.today(), 6000, "saved up")
    goals.refresh()
    goals._select(doomed)
    total_before = sum(g["saved_cents"] for g in db.goals())
    QMessageBox.exec = stub_confirm(checked=True)
    goals.delete_selected()
    check("ticking the box keeps the money",
          sum(g["saved_cents"] for g in db.goals()) == total_before,
          str([(g["name"], g["saved_cents"]) for g in db.goals()]))
    check("it lands in the goal that takes a share",
          db.get_goal(keeper)["saved_cents"] == 6000,
          str(db.get_goal(keeper)["saved_cents"]))
    check("and no income entry appears for it", db.income_total() == 0)

    print("\nShown and hidden")
    # The delete checks above emptied the log; put something back to count.
    db.add_expense(date.today(), 4500, "Groceries", "weekly shop")
    db.add_expense(date.today(), 2500, "Dining", "lunch")
    exp.refresh()
    rows_before = exp.model.rowCount()
    check("the ledger leads with a tick box", exp.model.columns[0].checkable)
    counted = exp.summary.text()
    exp.model.setData(exp.model.index(0, 0), Qt.CheckState.Unchecked,
                      Qt.ItemDataRole.CheckStateRole)
    check("unticking a row leaves it in the table", exp.model.rowCount() == rows_before)
    check("but takes it out of the total", exp.summary.text() != counted,
          exp.summary.text())
    check("and says how many are not counted", "not counted" in exp.summary.text(),
          exp.summary.text())
    check("the row is greyed out",
          exp.model.data(exp.model.index(0, 1), Qt.ItemDataRole.FontRole).strikeOut())

    exp._set_all_shown(False)
    check("hide all empties the total",
          exp.summary.text().startswith("0 expenses"), exp.summary.text())
    exp._set_all_shown(True)
    check("show all brings it back", exp.summary.text() == counted, exp.summary.text())

    # Same again for subscriptions, which the delete checks also cleared.
    db.add_subscription("Netflix", 1599, "Subscriptions", "monthly", date.today())
    window._navigate(3)
    subs.refresh()
    first = subs.table.item(0, 0)
    check("subscriptions lead with a tick box too", first is not None
          and first.checkState() == Qt.CheckState.Checked)
    monthly_before = subs.stat_monthly.value.text()
    subs._set_all_shown(False)
    check("hiding every subscription empties the commitment",
          subs.stat_monthly.value.text() != monthly_before,
          subs.stat_monthly.value.text())
    check("and the footer says so", "left out" in subs.summary.text(),
          subs.summary.text())
    subs._set_all_shown(True)
    check("showing them again restores it",
          subs.stat_monthly.value.text() == monthly_before,
          subs.stat_monthly.value.text())

    # ---------------------------------------------------------------- updates
    print("\nUpdates")
    # No network is touched: the handler is handed the answers a check would
    # have returned, which is the half that has to read correctly.
    said = []
    plain_information = QMessageBox.information
    plain_warning = QMessageBox.warning
    QMessageBox.information = lambda parent, title, text: said.append(text)
    QMessageBox.warning = lambda parent, title, text: said.append(text)

    names = [action.text() for action in window._settings_menu().actions()]
    check("settings offers a check for updates", "Check for updates..." in names, str(names))

    window._update_answer(
        updates.Update(branch="main", behind=0, ahead=0, dirty=False, subjects=())
    )
    check("an up-to-date copy says so", said[-1] == "This copy is up to date.", said[-1])

    window._update_answer(
        updates.Update(branch="main", behind=0, ahead=2, dirty=False, subjects=())
    )
    check("unpushed work is mentioned", "have not been pushed" in said[-1], said[-1])

    window._update_answer(updates.GitUnavailable("Git is not installed."))
    check("a failed check explains itself", said[-1] == "Git is not installed.", said[-1])

    before = len(said)
    # Turning the offer down must not reach for git at all -- an accepted one
    # would fast-forward this very checkout, which is not a test's business.
    QMessageBox.exec = stub_confirm(monkey_yes=False)
    window._update_answer(
        updates.Update(branch="main", behind=2, ahead=0, dirty=True,
                       subjects=("one", "two"))
    )
    check("declining an update pulls nothing", len(said) == before, str(said[before:]))

    QMessageBox.information = plain_information
    QMessageBox.warning = plain_warning

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for name in FAIL:
            print("  FAILED:", name)
    app.quit()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
