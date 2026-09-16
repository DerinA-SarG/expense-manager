"""Checks for goals, income, the category manager and CSV import/export.

Runs against the real widgets with dialogs stubbed, so the handlers themselves
are exercised rather than just the data layer underneath them.

    python tools/smoke_features.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from expman import csvio  # noqa: E402
from expman.app import MainWindow  # noqa: E402
from expman import updates  # noqa: E402
from expman.db import SCHEMA_VERSION, Database  # noqa: E402
from expman.import_dialog import ImportDialog  # noqa: E402
from expman.money import format_cents, parse_percent  # noqa: E402
from expman.widgets import PercentField  # noqa: E402
from expman.journey import STEPS as journey_steps  # noqa: E402
from expman.pages import goals as goals_page  # noqa: E402
from expman.pages import income as income_page  # noqa: E402

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    mark = "ok  " if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f"  -- {detail}" if detail and not condition else ""))


class StubDialog:
    """Stands in for a form dialog: accepted, with these values.

    `reset` and `reset_redistribute` are what the goal dialog reports back
    about its reset button, and default to the answer "leave it alone".
    """

    def __init__(self, values, reset=False, reset_redistribute=False):
        self._values = values
        self.reset = reset
        self.reset_redistribute = reset_redistribute
        self.reset_plan = []

    def __call__(self, *args, **kwargs):
        return self

    def exec(self):
        return 1

    def values(self):
        return dict(self._values)


def stub_confirm(self):
    """Auto-accept confirmation dialogs; without this a delete blocks forever."""
    return QMessageBox.StandardButton.Yes


def write(path: str, lines: list[str]) -> str:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


# --------------------------------------------------------------------- fixtures

DISCOVER = [
    "Trans. Date,Post Date,Description,Amount,Category",
    '01/15/2026,01/16/2026,"AMAZON.COM*XY12ABC",25.99,Merchandise',
    '01/16/2026,01/17/2026,"STARBUCKS #1234",5.45,Restaurants',
    '01/20/2026,01/21/2026,"DIRECTPAY FULL BALANCE",-450.00,Payments and Credits',
    '01/22/2026,01/23/2026,"SHELL OIL 12345678",42.10,Gasoline',
    '01/25/2026,01/26/2026,"KROGER #445",103.87,Supermarkets',
    '01/26/2026,01/27/2026,"RETURN - TARGET",-19.99,Merchandise',
]

CAPITAL_ONE = [
    "Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit",
    "2026-02-03,2026-02-04,1234,AMAZON.COM,Merchandise,25.99,",
    "2026-02-05,2026-02-06,1234,CAPITAL ONE AUTOPAY PYMT,Payment/Credit,,300.00",
    "2026-02-08,2026-02-09,1234,TRADER JOES,Grocery,87.33,",
    "2026-02-11,2026-02-12,1234,SHELL,Gas/Automotive,51.20,",
]

# Capital One deposit accounts: unsigned amounts, direction in its own column.
CAPITAL_ONE_BANK = [
    "Account Number,Transaction Description,Transaction Date,Transaction Type,Transaction Amount,Balance",
    "4795,Debit Card Purchase - WHATABURGER,08/03/26,Debit,9.07,129.73",
    "4795,Deposit from KINETIC PAYROLL,08/13/26,Credit,246.03,365.14",
    "4795,Debit Card Purchase - CIBO EXPRESS,08/02/26,Debit,6.48,138.80",
]

MESSY = [
    "Date;Merchant;Value",
    "2026-03-01;CORNER SHOP;\"1.234,50\"",
    "2026-03-02;REFUND;(15.00)",
    "not-a-date;BROKEN ROW;12.00",
]


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.exec = stub_confirm

    today = date.today()
    workdir = tempfile.mkdtemp(prefix="expman_feat_")
    db_path = os.path.join(workdir, "feat.db")
    window = MainWindow(Database(db_path))
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    db = window.db

    # ------------------------------------------------------------------ CSV
    print("\nCSV parsing")
    disc = csvio.load(write(os.path.join(workdir, "discover.csv"), DISCOVER))
    check("Discover layout detected", disc.profile.key == "discover", disc.profile.key)
    check("Discover purchases parsed", len(disc.expenses) == 4, str(len(disc.expenses)))
    check("Discover payment and refund become income", len(disc.incomes) == 2,
          f"income={len(disc.incomes)}")
    check(
        "issuer categories translated",
        {r.category for r in disc.expenses} == {"Shopping", "Dining", "Transport", "Groceries"},
        str({r.category for r in disc.expenses}),
    )

    cap = csvio.load(write(os.path.join(workdir, "capone.csv"), CAPITAL_ONE))
    check("Capital One layout detected", cap.profile.key == "capitalone_credit", cap.profile.key)
    check("debit rows are expenses, credit row is income",
          len(cap.expenses) == 3 and len(cap.incomes) == 1,
          f"exp={len(cap.expenses)} inc={len(cap.incomes)}")

    bank = csvio.load(write(os.path.join(workdir, "cobank.csv"), CAPITAL_ONE_BANK))
    check("Capital One bank layout detected", bank.profile.key == "capitalone_bank", bank.profile.key)
    check("direction column drives the split",
          len(bank.expenses) == 2 and len(bank.incomes) == 1,
          f"exp={len(bank.expenses)} inc={len(bank.incomes)}")
    check("deposit is recognised as payroll",
          bank.incomes[0].category == "Salary", bank.incomes[0].category)
    check(
        "unsigned debits import at face value",
        sorted(r.amount_cents for r in bank.expenses) == [648, 907],
        str(sorted(r.amount_cents for r in bank.expenses)),
    )
    check("two-digit years resolve to this century", str(bank.expenses[0].spent_on).startswith("2026"))

    messy = csvio.load(write(os.path.join(workdir, "messy.csv"), MESSY))
    check("semicolon delimiter sniffed", len(messy.headers) == 3, str(messy.headers))
    check("European decimal comma parsed", any(r.amount_cents == 123450 for r in messy.rows))
    check("parenthesised negative treated as income", len(messy.incomes) == 1)
    check("unreadable row flagged, not imported", messy.count("error") == 1)

    check("amount parser handles $1,299.99", csvio.parse_signed_money("$1,299.99") == 129999)
    check("amount parser handles -45.00", csvio.parse_signed_money("-45.00") == -4500)
    check("amount parser rejects junk", csvio.parse_signed_money("n/a") is None)

    # The compact form once divided thousands by 10,000, rendering $11,495.72
    # as "$1.1k" in the donut centre.
    from expman.money import format_compact
    check("compact keeps thousands honest", format_compact(1149572) == "$11.5k", format_compact(1149572))
    check("compact leaves small sums exact", format_compact(999900) == "$9,999.00", format_compact(999900))
    check("compact handles millions", format_compact(123456789) == "$1.2M", format_compact(123456789))

    # ------------------------------------------------------------ import flow
    print("\nImport")
    fingerprints = db.fingerprints()
    rows = csvio.parse_rows(
        csvio.read_table(os.path.join(workdir, "discover.csv"))[1],
        disc.profile,
        fingerprints=fingerprints,
    )
    inserted = db.add_expenses_bulk(
        [
            {
                "spent_on": r.spent_on,
                "amount_cents": r.amount_cents,
                "category": r.category,
                "description": r.description,
            }
            for r in rows
            if r.importable and not r.is_income
        ]
    )
    check("bulk insert writes every row", inserted == 4 and len(db.list_expenses()) == 4)

    again = csvio.load(
        os.path.join(workdir, "discover.csv"), fingerprints=db.fingerprints()
    )
    check("re-importing the same file finds only duplicate expenses", len(again.expenses) == 0)
    check("duplicates are counted, not dropped", again.count("duplicate") == 4)

    # ----------------------------------------------------- import dialog itself
    print("\nImport dialog")
    fresh_db = Database(os.path.join(workdir, "dialog.db"))
    dialog = ImportDialog(fresh_db, window.pal)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.show()
    dialog.load_path(os.path.join(workdir, "capone.csv"))

    check("dialog detects the layout", dialog.profile.key == "capitalone_credit")
    check("mapping pickers populate", dialog.field_boxes["debit"].currentData() == "Debit")
    check("preview lists every row", dialog.table.rowCount() == 4, str(dialog.table.rowCount()))
    check("import button counts expenses and income", dialog.import_button.text() == "Import 4",
          dialog.import_button.text())
    check("sign picker hidden for debit/credit files", not dialog.sign_box.isVisible())

    dialog.use_issuer.setChecked(False)
    check(
        "turning off issuer categories falls back",
        {r.category for r in dialog.rows if r.importable and not r.is_income}
        == {dialog.fallback.currentText()},
        str({r.category for r in dialog.rows if r.importable and not r.is_income}),
    )
    dialog.use_issuer.setChecked(True)

    dialog.capture_income.setChecked(False)
    check("income can be switched off", not any(r.importable and r.is_income for r in dialog.rows))
    dialog.capture_income.setChecked(True)
    check("and switched back on", any(r.importable and r.is_income for r in dialog.rows))

    dialog._do_import()
    check("dialog import writes both halves",
          dialog.imported_expenses == 3 and dialog.imported_income == 1,
          f"exp={dialog.imported_expenses} inc={dialog.imported_income}")
    check("expenses reached the database", len(fresh_db.list_expenses()) == 3)
    check("income reached the database", len(fresh_db.list_income()) == 1)
    check("income total is right", fresh_db.income_total() == 30000, str(fresh_db.income_total()))
    check(
        "amounts survived the dialog",
        sum(r["amount_cents"] for r in fresh_db.list_expenses()) == 2599 + 8733 + 5120,
    )

    reopened = ImportDialog(fresh_db, window.pal)
    reopened.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    reopened.show()
    reopened.load_path(os.path.join(workdir, "capone.csv"))
    check("second pass sees only duplicates", reopened.import_button.isEnabled() is False)

    # ------------------------------------------------------------------ export
    print("\nExport")
    out = os.path.join(workdir, "out.csv")
    written = csvio.export_expenses(db.list_expenses(), out)
    check("export writes every row", written == 4)
    roundtrip = csvio.load(out, fingerprints=set())
    check("export re-detects as our own format", roundtrip.profile.key == "expman")
    check("round-trip preserves all rows", len(roundtrip.expenses) == 4, str(len(roundtrip.expenses)))
    check(
        "round-trip preserves amounts",
        sorted(r.amount_cents for r in roundtrip.importable)
        == sorted(r["amount_cents"] for r in db.list_expenses()),
    )

    # --------------------------------------------------------------- categories
    print("\nCategory manager")
    groceries_before = len([r for r in db.list_expenses() if r['category'] == 'Groceries'])
    db.add_expense(today, 1500, "Grocerys", "typo category")
    check("typo category exists", "Grocerys" in db.categories())

    db.rename_category("Grocerys", "Groceries")
    check("merge removes the typo", "Grocerys" not in db.categories())
    merged = len([r for r in db.list_expenses() if r["category"] == "Groceries"])
    check(
        "merged expenses move across",
        merged == groceries_before + 1,
        f"{merged} vs {groceries_before} + 1",
    )

    db.ensure_category("Unused")
    db.delete_category("Unused")
    check("unused category deletes", "Unused" not in db.categories())

    try:
        db.delete_category("Groceries")
        check("deleting an in-use category is refused", False, "no error raised")
    except ValueError:
        check("deleting an in-use category is refused", True)

    db.rename_category("Dining", "Eating out")
    check("plain rename works", "Eating out" in db.categories() and "Dining" not in db.categories())
    check(
        "renamed expenses follow",
        all(r["category"] != "Dining" for r in db.list_expenses()),
    )

    usage = {u["name"]: u for u in db.category_usage()}
    check("usage counts expenses", usage["Groceries"]["expenses"] == merged,
          f'{usage["Groceries"]["expenses"]} vs {merged}')
    check("usage counts subscriptions", usage["Groceries"]["subscriptions"] == 0)

    # ------------------------------------------------------------------ income
    print("\nIncome page")
    inc = window.income
    income_page.IncomeDialog = StubDialog(
        {
            "received_on": today,
            "amount_cents": 250000,
            "source": "Salary",
            "description": "August pay",
            "notes": "",
        }
    )
    inc.add_income()
    check("income saved", db.income_total() == 250000, str(db.income_total()))
    check("income table shows it", inc.model.rowCount() == 1)
    check("income page leaves the empty state", inc.stack.currentIndex() == 0)

    income_page.IncomeDialog = StubDialog(
        {
            "received_on": today,
            "amount_cents": 1200,
            "source": "Side hustle",
            "description": "Odd job",
            "notes": "",
        }
    )
    inc.add_income()
    check("new source created on the fly", "Side hustle" in db.income_sources())
    check(
        "biggest source identified",
        inc.stat_top.value.text() == "Salary",
        inc.stat_top.value.text(),
    )

    spent_now = sum(a for _, a in db.category_totals())
    window.overview.period_box.setCurrentIndex(window.overview.period_box.count() - 1)
    net = db.income_total() - spent_now
    check(
        "overview net is income minus spending",
        window.overview.stat_net.value.text() == format_cents(net, db.currency),
        f"{window.overview.stat_net.value.text()} vs {format_cents(net, db.currency)}",
    )

    inc.table.selectAll()
    n = len(inc._selected_ids())
    inc.delete_selected()
    check(f"deleting all {n} income entries clears it", db.income_total() == 0)
    check("income falls back to the empty state", inc.stack.currentIndex() == 1)

    # ------------------------------------------------------------------- goals
    print("\nGoals page")
    page = window.goals
    goals_page.GoalDialog = StubDialog(
        {"name": "Emergency fund", "target_cents": 500000, "allocation_pct": 0.0, "notes": ""}
    )
    page.add_goal()
    check("goal created", len(db.goals()) == 1)
    check("new goal is selected", page.selected_id is not None)
    check("goals page leaves the empty state", page.stack.currentIndex() == 0)
    check("a tile was built for it", len(page.tiles) == 1)

    goals_page.ContributionDialog = StubDialog(
        {"made_on": today, "amount_cents": 125000, "note": "first"}
    )
    page.contribute_to_selected()
    goal = db.goals()[0]
    check("contribution recorded", goal["saved_cents"] == 125000, str(goal["saved_cents"]))
    check(
        "ring shows the right fraction",
        abs(page.tiles[goal["id"]].ring.ratio - 0.25) < 1e-9,
        str(page.tiles[goal["id"]].ring.ratio),
    )
    check(
        "still-to-save card is right",
        page.stat_left.value.text() == format_cents(375000, db.currency),
        page.stat_left.value.text(),
    )

    goals_page.ContributionDialog = StubDialog(
        {"made_on": today, "amount_cents": -25000, "note": "raided"}
    )
    page.contribute_to_selected()
    check("withdrawal reduces the goal", db.goals()[0]["saved_cents"] == 100000)

    goals_page.ContributionDialog = StubDialog(
        {"made_on": today, "amount_cents": 400000, "note": "done"}
    )
    page.contribute_to_selected()
    check("ring caps at full", page.tiles[db.goals()[0]["id"]].ring.ratio >= 1.0)

    goals_page.GoalDialog = StubDialog(
        {"name": "Emergency fund", "target_cents": 800000, "allocation_pct": 0.0, "notes": ""}
    )
    page.edit_selected()
    check("target can be raised", db.goals()[0]["target_cents"] == 800000)

    page.delete_selected()
    check("goal deleted", db.goals() == [])
    check(
        "its contributions went with it",
        db.conn.execute("SELECT COUNT(*) c FROM goal_contributions").fetchone()["c"] == 0,
    )
    check("goals fall back to the empty state", page.stack.currentIndex() == 1)

    # Goals are listed by name, so one added out of alphabetical order shifts
    # every goal after it along a cell. Tiles that stayed put would share a cell
    # and hide one another, leaving a goal counted but never drawn.
    for name in ("Bike", "Camera", "Desk", "Sofa"):
        goals_page.GoalDialog = StubDialog(
            {"name": name, "target_cents": 100000, "allocation_pct": 0.0, "notes": ""}
        )
        page.add_goal()
    goals_page.GoalDialog = StubDialog(
        {"name": "Amp", "target_cents": 100000, "allocation_pct": 0.0, "notes": ""}
    )
    page.add_goal()
    cells = {}
    for goal in db.goals():
        tile = page.tiles[goal["id"]]
        at = page.grid.indexOf(tile)
        cells[goal["name"]] = (
            page.grid.getItemPosition(at)[:2] if at != -1 else None
        )
    check("every goal has a tile in the grid", None not in cells.values(), str(cells))
    check(
        "no two goals share a cell",
        len(set(cells.values())) == len(cells),
        str(cells),
    )
    check(
        "a goal inserted first takes the first cell",
        cells.get("Amp") == (0, 0),
        str(cells),
    )
    check(
        "the footer counts what is on screen",
        page.summary.text().startswith("5 goals"),
        page.summary.text(),
    )

    for goal in db.goals():
        page.selected_id = goal["id"]
        page.delete_selected()
    check("goals cleared again", db.goals() == [])

    # ------------------------------------------------- setting aside from income
    print("\nIncome to goals")
    alloc_db = Database(os.path.join(workdir, "alloc.db"))
    emergency = alloc_db.add_goal("Emergency fund", 500000, allocation_pct=10)
    trip = alloc_db.add_goal("Trip", 200000, allocation_pct=5)
    manual_goal = alloc_db.add_goal("Manual only", 50000, allocation_pct=0)

    pay = alloc_db.add_income(date(2026, 8, 1), 200000, "Salary", "August pay")
    check(
        "logging income moves no goal on its own",
        all(g["saved_cents"] == 0 for g in alloc_db.goals()),
        str([(g["name"], g["saved_cents"]) for g in alloc_db.goals()]),
    )
    plan = alloc_db.pending_plan()
    quoted = {share["name"]: share["cents"] for share in plan["shares"]}
    check("the entry is counted as waiting", plan["count"] == 1, str(plan["count"]))
    check("the split is worked out and shown", plan["total_cents"] == 30000, str(plan))
    check("each goal is quoted its own share", quoted == {"Emergency fund": 20000, "Trip": 10000},
          str(quoted))
    check("a 0% goal is not in the plan", "Manual only" not in quoted)

    applied = alloc_db.apply_pending()
    saved = {g["name"]: g["saved_cents"] for g in alloc_db.goals()}
    check("applying the plan sets 10% of income aside", saved["Emergency fund"] == 20000, str(saved))
    check("a second goal takes its own share", saved["Trip"] == 10000, str(saved))
    check("a 0% goal is left alone", saved["Manual only"] == 0, str(saved))
    check("what was applied matches what was shown", applied["total_cents"] == plan["total_cents"])
    check("total allocation is reported", alloc_db.total_allocation_pct() == 15)
    check("nothing is left waiting", alloc_db.pending_plan()["count"] == 0)

    alloc_db.apply_pending()
    check(
        "pressing update again sets nothing aside twice",
        alloc_db.get_goal(emergency)["saved_cents"] == 20000,
        str(alloc_db.get_goal(emergency)["saved_cents"]),
    )

    alloc_db.add_contribution(emergency, date(2026, 8, 5), 7500, "birthday cash")
    alloc_db.update_income(pay, date(2026, 8, 1), 300000, "Salary", "August pay, corrected")
    g = alloc_db.get_goal(emergency)
    check("editing applied income re-cuts its share", g["from_income_cents"] == 30000, str(g))
    check("a hand-entered top-up survives the recut", g["saved_cents"] == 30000 + 7500, str(g))
    check("and it is not offered again", alloc_db.pending_plan()["count"] == 0)

    before = alloc_db.get_goal(emergency)["from_income_cents"]
    alloc_db.update_goal(emergency, "Emergency fund", 500000, allocation_pct=20)
    after = alloc_db.get_goal(emergency)["from_income_cents"]
    check("raising the share leaves money already set aside alone", after == before,
          f"{before} -> {after}")

    alloc_db.add_income(date(2026, 8, 15), 100000, "Freelance", "side job")
    check(
        "income logged after the change is quoted at the new share",
        alloc_db.pending_plan()["by_goal"][emergency] == 20000,
        str(alloc_db.pending_plan()["by_goal"]),
    )
    alloc_db.apply_pending()
    g = alloc_db.get_goal(emergency)
    check(
        "the new share applies once it is set aside",
        g["from_income_cents"] == before + 20000,
        str(g["from_income_cents"]),
    )
    check("the manual top-up is still untouched", g["saved_cents"] - g["from_income_cents"] == 7500)

    # An entry nobody has applied yet is simply re-quoted from the new figure.
    waiting = alloc_db.add_income(date(2026, 8, 20), 50000, "Freelance", "another job")
    alloc_db.update_income(waiting, date(2026, 8, 20), 80000, "Freelance", "another job, fixed")
    check("editing an entry that is still waiting leaves it waiting",
          alloc_db.is_allocated(waiting) is False)
    check(
        "and re-quotes it from the corrected amount",
        alloc_db.pending_plan()["income_cents"] == 80000,
        str(alloc_db.pending_plan()["income_cents"]),
    )
    held = sum(g["saved_cents"] for g in alloc_db.goals())
    income_before = alloc_db.income_total()
    alloc_db.skip_pending()
    check("skipping sets nothing aside", sum(g["saved_cents"] for g in alloc_db.goals()) == held)
    check("and clears the queue", alloc_db.pending_plan()["count"] == 0)
    check("and leaves the income itself alone", alloc_db.income_total() == income_before)

    # A correction to an old payslip is a correction to that payslip: it is
    # re-cut at the rate it was originally split at, not today's.
    alloc_db.update_income(pay, date(2026, 8, 1), 400000, "Salary", "August pay, again")
    g = alloc_db.get_goal(emergency)
    check(
        "editing old income re-cuts it at the rate it was set aside at",
        g["from_income_cents"] == 40000 + 20000,
        str(g["from_income_cents"]),
    )
    alloc_db.delete_income([pay])
    g = alloc_db.get_goal(emergency)
    check(
        "deleting income takes its share back out",
        g["from_income_cents"] == 20000,
        str(g["from_income_cents"]),
    )
    check("and still leaves the manual money", g["saved_cents"] == 20000 + 7500, str(g))

    # A CSV import is just many income rows, so it must queue up the same way.
    before = alloc_db.get_goal(trip)["saved_cents"]
    alloc_db.add_income_bulk(
        [
            {"received_on": date(2026, 9, i + 1), "amount_cents": 100000,
             "source": "Salary", "description": f"imported {i}"}
            for i in range(3)
        ]
    )
    check("imported income waits with the rest", alloc_db.pending_plan()["count"] == 3,
          str(alloc_db.pending_plan()["count"]))
    alloc_db.apply_pending()
    check(
        "imported income is set aside too",
        alloc_db.get_goal(trip)["saved_cents"] == before + 3 * 5000,
        str(alloc_db.get_goal(trip)["saved_cents"]),
    )

    # The goals page should surface a plan that claims more than comes in.
    alloc_db.update_goal(trip, "Trip", 200000, allocation_pct=95)
    check("over-allocation is detectable", alloc_db.total_allocation_pct() > 100,
          str(alloc_db.total_allocation_pct()))
    check("median income is available for the hint", alloc_db.typical_income() == 100000,
          str(alloc_db.typical_income()))

    # ------------------------------------------------------- when a goal fills up
    print("\nWhen a goal fills up")
    spill_db = Database(os.path.join(workdir, "spill.db"))
    nearly = spill_db.add_goal("Nearly there", 10000, allocation_pct=20)
    big = spill_db.add_goal("Big one", 1000000, allocation_pct=30)
    slow = spill_db.add_goal("Slow", 1000000, allocation_pct=10)

    spill_db.add_income(date(2026, 8, 1), 100000, "Salary", "pay")
    spill = spill_db.pending_plan()
    landed = {share["name"]: share["cents"] for share in spill["shares"]}
    check("a full goal takes only what fits", landed["Nearly there"] == 10000, str(landed))
    check(
        "what will not fit goes to the goals that take a share",
        landed["Big one"] == 30000 + 7500 and landed["Slow"] == 10000 + 2500,
        str(landed),
    )
    check("the whole share of income is still set aside", spill["total_cents"] == 60000,
          str(spill["total_cents"]))
    check("with nothing left unplaced", spill["unplaced_cents"] == 0)

    spill_db.apply_pending()
    check(
        "no goal is left over its target",
        all(g["saved_cents"] <= g["target_cents"] for g in spill_db.goals()),
        str([(g["name"], g["saved_cents"], g["target_cents"]) for g in spill_db.goals()]),
    )
    notes = [
        r["note"]
        for r in spill_db.conn.execute("SELECT note FROM goal_contributions")
    ]
    check("the overflow says so on the contribution", any("overflow" in n for n in notes),
          str(notes))
    check("and the goal that filled up says that", any("target reached" in n for n in notes),
          str(notes))

    # Money handed to a full goal by hand follows the same rule.
    hand_plan = spill_db.contribution_plan(nearly, 5000)
    check("a hand-entered amount stops at the target too", hand_plan["into_cents"] == 0,
          str(hand_plan))
    check(
        "and the rest is offered to the goals with room",
        sum(share["cents"] for share in hand_plan["shares"]) == 5000,
        str(hand_plan),
    )
    held = {g["name"]: g["saved_cents"] for g in spill_db.goals()}
    spill_db.contribute(nearly, date(2026, 8, 2), 5000, "bonus")
    now = {g["name"]: g["saved_cents"] for g in spill_db.goals()}
    check("which is where it actually lands", now["Nearly there"] == held["Nearly there"],
          str(now))
    check("every cent of it still saved", sum(now.values()) == sum(held.values()) + 5000,
          str(now))
    spill_db.contribute(big, date(2026, 8, 3), -2000, "took it back")
    check(
        "a withdrawal is left alone",
        spill_db.get_goal(big)["saved_cents"] == now["Big one"] - 2000,
        str(spill_db.get_goal(big)["saved_cents"]),
    )

    # With every goal full there is nowhere for it, and that is said out loud
    # rather than the money being quietly dropped.
    full_db = Database(os.path.join(workdir, "full.db"))
    only = full_db.add_goal("Only goal", 5000, allocation_pct=50)
    full_db.add_income(date(2026, 8, 1), 100000, "Salary", "pay")
    full = full_db.pending_plan()
    check("a lone goal takes only what fits", full["total_cents"] == 5000, str(full))
    check("and the rest is reported, not lost", full["unplaced_cents"] == 45000, str(full))
    full_db.apply_pending()
    check("the goal stops exactly at its target",
          full_db.get_goal(only)["saved_cents"] == 5000,
          str(full_db.get_goal(only)["saved_cents"]))

    # ----------------------------------------------------- goals already over
    print("\nGoals already over target")
    over_db = Database(os.path.join(workdir, "over.db"))
    overfull = over_db.add_goal("Overfull", 10000, allocation_pct=20)
    room = over_db.add_goal("Room", 100000, allocation_pct=30)
    more_room = over_db.add_goal("More room", 100000, allocation_pct=10)
    over_db.add_contribution(overfull, date(2026, 8, 1), 16000, "saved before the rule")

    excess = over_db.excess_plan()
    going = {share["name"]: share["cents"] for move in excess["moves"] for share in move["shares"]}
    check("money above a target is spotted", excess["excess_cents"] == 6000, str(excess))
    check("and offered to the goals with room",
          going == {"Room": 4500, "More room": 1500}, str(going))

    before_total = sum(g["saved_cents"] for g in over_db.goals())
    over_db.settle_excess()
    after = {g["name"]: g["saved_cents"] for g in over_db.goals()}
    check("settling leaves the goal exactly at its target", after["Overfull"] == 10000, str(after))
    check("its money is not lost", sum(after.values()) == before_total, str(after))
    check("it lands where the plan said",
          after["Room"] == 4500 and after["More room"] == 1500, str(after))
    check("and there is nothing left over", over_db.excess_plan()["moves"] == [])

    # ------------------------------------------------------- resetting a goal
    print("\nResetting a goal")
    reset_db = Database(os.path.join(workdir, "reset.db"))
    keep = reset_db.add_goal("Keep me", 100000, allocation_pct=25)
    elsewhere = reset_db.add_goal("Elsewhere", 100000, allocation_pct=10)
    reset_db.add_contribution(keep, date(2026, 8, 1), 20000, "saved")

    reset_db.reset_goal(keep)
    goal = reset_db.get_goal(keep)
    check("a reset empties the goal", goal["saved_cents"] == 0, str(goal["saved_cents"]))
    check("its contributions go with it", goal["contributions"] == 0)
    check("but the goal itself stays", goal["name"] == "Keep me")
    check("with its target and its share intact",
          goal["target_cents"] == 100000 and goal["allocation_pct"] == 25, str(dict(goal)))
    check("and the other goals are untouched",
          reset_db.get_goal(elsewhere)["saved_cents"] == 0)

    reset_db.add_contribution(keep, date(2026, 8, 2), 20000, "saved again")
    total_before = sum(g["saved_cents"] for g in reset_db.goals())
    moved = reset_db.reset_goal(keep, redistribute=True)
    check("resetting with the money kept hands it on",
          sum(g["saved_cents"] for g in reset_db.goals()) == total_before,
          str([(g["name"], g["saved_cents"]) for g in reset_db.goals()]))
    check("it lands in the goal that takes a share",
          reset_db.get_goal(elsewhere)["saved_cents"] == 20000,
          str(reset_db.get_goal(elsewhere)["saved_cents"]))
    check("and the reset goal starts again at nothing",
          reset_db.get_goal(keep)["saved_cents"] == 0)
    check("the money says where it came from",
          moved and moved[0]["name"] == "Elsewhere", str(moved))

    # The same thing through the dialog the user actually sees.
    page.db = db
    dialog_goal = db.add_goal("Through the dialog", 100000, allocation_pct=0)
    db.add_contribution(dialog_goal, today, 30000, "saved")
    page.refresh()
    page._select(dialog_goal)
    goals_page.GoalDialog = StubDialog(
        {"name": "Through the dialog", "target_cents": 100000,
         "allocation_pct": 0.0, "notes": ""},
        reset=True,
    )
    page.edit_selected()
    check("the edit dialog can reset a goal",
          db.get_goal(dialog_goal)["saved_cents"] == 0,
          str(db.get_goal(dialog_goal)["saved_cents"]))
    check("and the goal survives it", db.get_goal(dialog_goal) is not None)
    db.delete_goal(dialog_goal)
    page.refresh()

    # ------------------------------------------------- the steps in the sidebar
    print("\nThe steps in the sidebar")
    panel = window.journey
    panel.reset()
    # Something for the last step to actually do: with no goal taking a share,
    # updating them would be a no-op, and a no-op is not a step done.
    step_goal = db.add_goal("Step check", 500000, allocation_pct=10)
    check("a session starts with nothing ticked", panel.done == set(), str(panel.done))
    check("the first step is the one being asked for", panel.track.current == 0,
          str(panel.track.current))

    income_page.IncomeDialog = StubDialog(
        {
            "received_on": today,
            "amount_cents": 180000,
            "source": "Salary",
            "description": "step check",
            "notes": "",
        }
    )
    window.income.add_income()
    check("logging income ticks its step", "income" in panel.done, str(panel.done))
    check("and the next one is asked for", panel.track.current == 1, str(panel.track.current))

    window.goals.apply_pending()
    check("updating goals ticks the last step", "goals" in panel.done, str(panel.done))
    check("the rail fills as steps are ticked", panel.track._target_fill == 1.0,
          str(panel.track._target_fill))
    window.income.add_income()
    check("doing something twice is not an error", "income" in panel.done)

    check(
        "the money the step set aside is really there",
        db.get_goal(step_goal)["saved_cents"] == 18000,
        str(db.get_goal(step_goal)["saved_cents"]),
    )
    db.delete_goal(step_goal)
    window.income.table.selectAll()
    window.income.delete_selected()
    page.refresh()

    window.go_to(0)
    check("a step click navigates", window.stack.currentIndex() == 0)
    check("and the sidebar button follows it", window.nav_buttons.button(0).isChecked())

    from expman.journey import JourneyPanel  # noqa: E402

    fresh = JourneyPanel(window.pal)
    check("a new session starts empty again", fresh.done == set(), str(fresh.done))
    check("every step points at a real page",
          all(0 <= index < len(window.pages) for _, _, index in journey_steps),
          str(journey_steps))

    # ------------------------------------------------- leaving rows out

    print("\nHiding rows from a page's figures")
    hide_db = Database(os.path.join(workdir, "hide.db"))
    keep = hide_db.add_expense(date(2026, 8, 1), 5000, "Groceries", "counted")
    drop = hide_db.add_expense(date(2026, 8, 2), 3000, "Dining", "not counted")
    paid = hide_db.add_income(date(2026, 8, 1), 200000, "Salary", "counted")
    gift = hide_db.add_income(date(2026, 8, 3), 50000, "Gift", "not counted")

    check("everything counts to begin with", hide_db.expense_span() is not None)
    check("a row starts out shown",
          hide_db.list_expenses()[0]["hidden"] == 0,
          str(hide_db.list_expenses()[0]["hidden"]))

    hide_db.set_hidden("expenses", [drop], True)
    hide_db.set_hidden("income", [gift], True)
    shown = {r["id"]: r["hidden"] for r in hide_db.list_expenses()}
    check("hiding sets the flag", shown[drop] == 1 and shown[keep] == 0, str(shown))
    check("the row is still there", len(hide_db.list_expenses()) == 2)

    check("totals still count everything by default",
          hide_db.income_total() == 250000, str(hide_db.income_total()))
    check("and skip hidden rows when asked",
          hide_db.income_total(include_hidden=False) == 200000,
          str(hide_db.income_total(include_hidden=False)))
    spent = dict(hide_db.category_totals(include_hidden=False))
    check("a hidden expense leaves its category out", "Dining" not in spent, str(spent))
    check("while the shown one stays", spent.get("Groceries") == 5000, str(spent))
    sources = dict(hide_db.income_by_source(include_hidden=False))
    check("a hidden source drops out too", "Gift" not in sources, str(sources))

    hide_db.set_hidden("expenses", None, True)
    check("everything can be hidden at once",
          all(r["hidden"] for r in hide_db.list_expenses()))
    check("and the figures go to nothing",
          hide_db.category_totals(include_hidden=False) == [])
    hide_db.set_hidden("expenses", None, False)
    check("and shown again", not any(r["hidden"] for r in hide_db.list_expenses()))

    try:
        hide_db.set_hidden("goals", [1], True)
        guarded = False
    except ValueError:
        guarded = True
    check("only the three ledgers can hide rows", guarded)

    sub = hide_db.add_subscription("Netflix", 1599, "Subscriptions", "monthly",
                                   date(2026, 8, 1))
    hide_db.set_hidden("subscriptions", [sub], True)
    check("subscriptions carry the flag too",
          hide_db.list_subscriptions()[0]["hidden"] == 1)

    # ---------------------------------------------- a file from an older build
    print("\nOpening a database from an older build")
    # Before goals could take a share of income, goal_contributions had no
    # income_id; it arrives by ALTER TABLE, which cannot carry ON DELETE CASCADE
    # with it. That left the reference enforced but inert, so deleting an income
    # entry that had fed a goal failed on the constraint instead of taking its
    # contributions with it -- on the income page, a delete that did nothing.
    legacy_path = os.path.join(workdir, "legacy.db")
    legacy = Database(legacy_path)
    legacy_goal = legacy.add_goal("Old goal", 100000, allocation_pct=10)
    legacy_income = legacy.add_income(date(2026, 7, 1), 200000, "Salary", "old pay")
    legacy.apply_pending()
    legacy.add_contribution(legacy_goal, date(2026, 7, 2), 5000, "by hand")
    legacy.conn.executescript(
        """
        PRAGMA foreign_keys = OFF;
        ALTER TABLE goal_contributions RENAME TO goal_contributions_old;
        CREATE TABLE goal_contributions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id        INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
            made_on        TEXT    NOT NULL,
            amount_cents   INTEGER NOT NULL,
            note           TEXT    NOT NULL DEFAULT '',
            created_at     TEXT    NOT NULL,
            income_id      INTEGER REFERENCES income(id),
            allocation_pct REAL    NOT NULL DEFAULT 0
        );
        INSERT INTO goal_contributions (id, goal_id, made_on, amount_cents, note,
                                        created_at, income_id, allocation_pct)
             SELECT id, goal_id, made_on, amount_cents, note,
                    created_at, income_id, allocation_pct
               FROM goal_contributions_old;
        DROP TABLE goal_contributions_old;
        """
    )
    legacy.conn.commit()
    legacy.close()

    stale = sqlite3.connect(legacy_path)
    try:
        stale.execute("PRAGMA foreign_keys = ON")
        stale.execute("DELETE FROM income WHERE id = ?", (legacy_income,))
        blocked = False
    except sqlite3.IntegrityError:
        blocked = True
    finally:
        stale.close()
    check("the old shape is the one that blocked deletes", blocked)

    repaired = Database(legacy_path)
    cascades = {
        row["table"]: row["on_delete"]
        for row in repaired.conn.execute("PRAGMA foreign_key_list(goal_contributions)")
    }
    check("opening it puts the cascade back", cascades.get("income") == "CASCADE",
          str(cascades))
    check(
        "money already set aside survives the rebuild",
        repaired.get_goal(legacy_goal)["saved_cents"] == 20000 + 5000,
        str(repaired.get_goal(legacy_goal)["saved_cents"]),
    )
    check("the file reports the newer schema version",
          repaired.get_setting("schema_version") == SCHEMA_VERSION,
          repaired.get_setting("schema_version"))
    check("income from an older file deletes", repaired.delete_income([legacy_income]) == 1)
    check(
        "and takes only its own share with it",
        repaired.get_goal(legacy_goal)["saved_cents"] == 5000,
        str(repaired.get_goal(legacy_goal)["saved_cents"]),
    )
    check("the file is left consistent",
          repaired.conn.execute("PRAGMA foreign_key_check").fetchall() == [])
    repaired.close()

    # ------------------------------------------------------- typing a per cent
    print("\nEntering a share")
    check("a blank share means none", parse_percent("") == 0.0)
    check("a plain number reads as a share", parse_percent("15") == 15.0)
    check("a decimal share survives", parse_percent("12.5") == 12.5)
    check("a comma decimal reads the same", parse_percent("12,5") == 12.5)
    check("a typed per cent sign is ignored", parse_percent("15%") == 15.0)
    for bad, label in (("-4", "below nothing"), ("101", "over everything"), ("abc", "not a number")):
        try:
            parse_percent(bad)
            rejected = False
        except ValueError:
            rejected = True
        check(f"a share {label} is rejected", rejected, bad)

    field = PercentField()
    field.set_value(0)
    check("nothing set aside leaves the box empty", field.edit.text() == "", field.edit.text())
    field.set_value(12.5)
    check("a share is shown without padding", field.edit.text() == "12.5", field.edit.text())
    check("and reads back as it was set", field.value() == 12.5)
    field.edit.setText("7,5")
    check("what is typed is what is read", field.value() == 7.5, str(field.value()))
    check("the sign sits outside the box", field.sign.text() == "%")

    # -------------------------------------------- moving a deleted goal's money
    print("\nDeleting a goal, keeping its money")
    share_db = Database(os.path.join(workdir, "share.db"))
    doomed = share_db.add_goal("Old plan", 100000, allocation_pct=30)
    big = share_db.add_goal("Big", 500000, allocation_pct=20)
    small = share_db.add_goal("Small", 100000, allocation_pct=5)
    manual = share_db.add_goal("By hand", 100000, allocation_pct=0)
    share_db.add_contribution(doomed, date(2026, 8, 1), 10001, "saved up")

    plan = share_db.redistribution_plan(doomed)
    landing = {row["name"]: row["cents"] for row in plan}
    check("the split reaches the goals that take a share", set(landing) == {"Big", "Small"},
          str(landing))
    check("a manual-only goal is not in it", "By hand" not in landing)
    check("every cent is handed out", sum(landing.values()) == 10001, str(landing))
    check("and in proportion to the shares taken", landing["Big"] == 8001, str(landing))
    check("odd cents go to the largest share", landing["Small"] == 2000, str(landing))

    before_total = sum(g["saved_cents"] for g in share_db.goals())
    share_db.delete_goal(doomed, redistribute=True)
    after = {g["name"]: g["saved_cents"] for g in share_db.goals()}
    check("the goal is gone", "Old plan" not in after, str(after))
    check("its money is not", sum(after.values()) == before_total, str(after))
    check("it landed where the plan said", after["Big"] == 8001 and after["Small"] == 2000,
          str(after))
    moved = share_db.conn.execute(
        "SELECT note, income_id FROM goal_contributions WHERE goal_id = ?", (big,)
    ).fetchall()
    check("the money says where it came from", moved[0]["note"] == "Moved from Old plan",
          moved[0]["note"])
    check("and is not tied to any income entry", moved[0]["income_id"] is None)
    check("nothing was added to the income page", share_db.income_total() == 0)

    # Deleting without the offer is still a plain delete.
    share_db.add_contribution(manual, date(2026, 8, 2), 5000, "cash")
    kept = sum(g["saved_cents"] for g in share_db.goals())
    share_db.delete_goal(manual)
    check("deleting without moving the money takes it with it",
          sum(g["saved_cents"] for g in share_db.goals()) == kept - 5000)

    lonely_db = Database(os.path.join(workdir, "lonely.db"))
    only = lonely_db.add_goal("Only one", 100000, allocation_pct=10)
    lonely_db.add_contribution(only, date(2026, 8, 1), 2500, "saved")
    check("with nowhere to move it to there is nothing to offer",
          lonely_db.redistribution_plan(only) == [])

    # ---------------------------------------------------------------- updates
    print("\nChecking for updates")
    # No network here: a directory that is not a checkout answers before git
    # ever reaches for one.
    nowhere = os.path.join(workdir, "not-a-checkout")
    os.makedirs(nowhere, exist_ok=True)
    check("a folder outside a checkout has no repository",
          updates.repo_root(Path(nowhere)) is None)
    try:
        updates.check(Path(nowhere))
        refused = False
    except updates.GitUnavailable:
        refused = True
    except Exception:
        refused = False
    check("and checking there says so rather than reaching out", refused)
    check("the app itself knows where it came from",
          updates.repo_root() is None or (updates.repo_root() / "expman").is_dir())
    check("a source run is not a frozen build", updates.is_frozen() is False)

    # ------------------------------------------------------------ first paint
    print("\nLanding page")
    landing_db = Database(os.path.join(workdir, "landing.db"))
    landing_db.add_expense(date.today(), 4321, "Groceries", "shop")
    fresh = MainWindow(landing_db)
    fresh.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    fresh.show()
    # No navigation: this is exactly what the user sees on launch.
    check(
        "Overview arrives populated, without navigating first",
        fresh.overview.stat_total.value.text() == format_cents(4321, landing_db.currency),
        fresh.overview.stat_total.value.text(),
    )
    fresh.close()

    # -------------------------------------------------- subscription schedules
    print("\nSubscription schedules")
    sched = Database(os.path.join(workdir, "sched.db"))
    today = date(2026, 8, 28)

    def sub_charges(sid):
        return sorted(
            e["spent_on"] for e in sched.list_expenses() if e["subscription_id"] == sid
        )

    claude = sched.add_subscription(
        "Claude", 2135, "Subscriptions", "monthly", date(2026, 8, 18)
    )
    check(
        "the start date is the first charge, with no second date to set",
        sched.get_subscription(claude)["next_due"] == "2026-08-18",
    )
    check("a charge already run up posts", sched.post_due_subscriptions(today) == 1)
    check("on its billing date", sub_charges(claude) == ["2026-08-18"])
    check("relaunching posts it no second time", sched.post_due_subscriptions(today) == 0)

    gym = sched.add_subscription(
        "Gym", 4000, "Subscriptions", "monthly", date(2026, 5, 31)
    )
    sched.post_due_subscriptions(today)
    check(
        "a back-dated subscription catches up, month ends clamped",
        sub_charges(gym) == ["2026-05-31", "2026-06-30", "2026-07-31"],
        str(sub_charges(gym)),
    )

    sched.update_subscription(
        claude, "Claude", 2135, "Subscriptions", "monthly", date(2026, 8, 20)
    )
    sched.post_due_subscriptions(today)
    check(
        "moving the billing day does not bill the same month twice",
        sub_charges(claude) == ["2026-08-18"],
        str(sub_charges(claude)),
    )
    check(
        "the next charge moves to the new day",
        sched.get_subscription(claude)["next_due"] == "2026-09-20",
        sched.get_subscription(claude)["next_due"],
    )
    sched.close()

    # ------------------------------------------------------------ delete data
    print("\nDelete data")
    from expman.dialogs import DeleteEverythingDialog

    wipe_db = Database(os.path.join(workdir, "wipe.db"))
    sid = wipe_db.add_subscription(
        "Netflix", 1599, "Subscriptions", "monthly", date(2026, 5, 1), date(2026, 5, 1)
    )
    wipe_db.post_due_subscriptions(date(2026, 8, 1))
    wipe_db.add_expense(date(2026, 8, 2), 5000, "Groceries", "manual shop")
    wipe_db.add_income(date(2026, 8, 3), 200000, "Salary", "pay")
    wipe_goal = wipe_db.add_goal("Trip", 100000)
    wipe_db.add_contribution(wipe_goal, date(2026, 8, 4), 25000)

    wipe = DeleteEverythingDialog(wipe_db)
    wipe.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    wipe.show()

    check("delete is blocked until the word is typed", not wipe.delete_button.isEnabled())
    wipe.confirm_field.setText("delete")
    check("the check is case-sensitive", not wipe.delete_button.isEnabled())
    wipe.confirm_field.setText("DELETE")
    check("typing it enables delete", wipe.delete_button.isEnabled())

    for key in wipe.switches:
        wipe.switches[key].setChecked(False)
    check("nothing selected blocks it again", not wipe.delete_button.isEnabled())

    # Clear only income; everything else must survive untouched.
    wipe.switches["income"].setChecked(True)
    wipe.backup_field.setChecked(True)
    wipe._wipe()
    check("selective wipe removes only what was ticked", wipe_db.income_total() == 0)
    check("expenses survived a selective wipe", len(wipe_db.list_expenses()) == 5,
          str(len(wipe_db.list_expenses())))
    check("goals survived a selective wipe", len(wipe_db.goals()) == 1)
    check("a backup file was written", wipe.backup_path and wipe.backup_path.exists())

    restored = Database(str(wipe.backup_path))
    check("the backup still holds the deleted income", restored.income_total() == 200000,
          str(restored.income_total()))

    # Clearing subscriptions takes their posted charges but not manual entries.
    manual = len([r for r in wipe_db.list_expenses() if r["subscription_id"] is None])
    wipe2 = DeleteEverythingDialog(wipe_db)
    wipe2.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    wipe2.show()
    for key in wipe2.switches:
        wipe2.switches[key].setChecked(key == "subscriptions")
    wipe2.backup_field.setChecked(False)
    wipe2.confirm_field.setText("DELETE")
    wipe2._wipe()
    check("subscriptions take their posted charges", len(wipe_db.list_subscriptions()) == 0)
    check(
        "hand-entered expenses are not collateral",
        len([r for r in wipe_db.list_expenses() if r["subscription_id"] is None]) == manual,
        str(len(wipe_db.list_expenses())),
    )

    wipe3 = DeleteEverythingDialog(wipe_db)
    wipe3.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    wipe3.show()
    wipe3.backup_field.setChecked(False)
    wipe3.confirm_field.setText("DELETE")
    wipe3._wipe()
    left = wipe_db.counts()
    check("wiping everything empties the database",
          all(v == 0 for k, v in left.items() if k != "categories"), str(left))
    check("default categories are put back", left["categories"] == 10, str(left["categories"]))

    # ------------------------------------------------------------------ wiring
    print("\nWiring")
    for index in range(len(window.pages)):
        window._navigate(index)
    check("all five pages navigate", window.stack.currentIndex() == 4,
          str(window.stack.currentIndex()))
    window._toggle_theme()
    check("theme reaches every page", window.goals.pal["name"] == window.pal["name"])
    # Hidden pages are refreshed when opened rather than on every change, so a
    # currency switch should reach the Goals page the moment it is navigated to.
    window._navigate(0)
    window._set_currency("£")
    check(
        "a hidden page has not rebuilt yet",
        "£" not in window.goals.stat_target.value.text(),
        window.goals.stat_target.value.text(),
    )
    window._navigate(4)
    check(
        "opening it picks the change up",
        "£" in window.goals.stat_target.value.text(),
        window.goals.stat_target.value.text(),
    )

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for name in FAIL:
        print("  FAILED:", name)
    app.quit()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
