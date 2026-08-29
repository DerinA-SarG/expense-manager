"""Checks for goals, income, the category manager and CSV import/export.

Runs against the real widgets with dialogs stubbed, so the handlers themselves
are exercised rather than just the data layer underneath them.

    python tools/smoke_features.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from expman import csvio  # noqa: E402
from expman.app import MainWindow  # noqa: E402
from expman.db import Database  # noqa: E402
from expman.import_dialog import ImportDialog  # noqa: E402
from expman.money import format_cents  # noqa: E402
from expman.pages import goals as goals_page  # noqa: E402
from expman.pages import income as income_page  # noqa: E402

PASS, FAIL = [], []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASS if condition else FAIL).append(label)
    mark = "ok  " if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f"  -- {detail}" if detail and not condition else ""))


class StubDialog:
    def __init__(self, values):
        self._values = values

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

    # ------------------------------------------------- setting aside from income
    print("\nIncome to goals")
    alloc_db = Database(os.path.join(workdir, "alloc.db"))
    emergency = alloc_db.add_goal("Emergency fund", 500000, allocation_pct=10)
    trip = alloc_db.add_goal("Trip", 200000, allocation_pct=5)
    manual_goal = alloc_db.add_goal("Manual only", 50000, allocation_pct=0)

    pay = alloc_db.add_income(date(2026, 8, 1), 200000, "Salary", "August pay")
    saved = {g["name"]: g["saved_cents"] for g in alloc_db.goals()}
    check("10% of income lands in the goal", saved["Emergency fund"] == 20000, str(saved))
    check("a second goal takes its own share", saved["Trip"] == 10000, str(saved))
    check("a 0% goal is left alone", saved["Manual only"] == 0, str(saved))
    check("total allocation is reported", alloc_db.total_allocation_pct() == 15)

    alloc_db.allocate_income(pay)
    check(
        "re-allocating the same income does not double it",
        alloc_db.get_goal(emergency)["saved_cents"] == 20000,
        str(alloc_db.get_goal(emergency)["saved_cents"]),
    )

    alloc_db.add_contribution(emergency, date(2026, 8, 5), 7500, "birthday cash")
    alloc_db.update_income(pay, date(2026, 8, 1), 300000, "Salary", "August pay, corrected")
    g = alloc_db.get_goal(emergency)
    check("editing income re-cuts its share", g["from_income_cents"] == 30000, str(g))
    check("a hand-entered top-up survives the recut", g["saved_cents"] == 30000 + 7500, str(g))

    before = alloc_db.get_goal(emergency)["from_income_cents"]
    alloc_db.update_goal(emergency, "Emergency fund", 500000, allocation_pct=20)
    after = alloc_db.get_goal(emergency)["from_income_cents"]
    check("raising the share leaves money already set aside alone", after == before,
          f"{before} -> {after}")

    alloc_db.add_income(date(2026, 8, 15), 100000, "Freelance", "side job")
    g = alloc_db.get_goal(emergency)
    check(
        "the new share applies to income logged after the change",
        g["from_income_cents"] == before + 20000,
        str(g["from_income_cents"]),
    )
    check("the manual top-up is still untouched", g["saved_cents"] - g["from_income_cents"] == 7500)

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

    # A CSV import is just many income rows, so it must allocate the same way.
    before = alloc_db.get_goal(trip)["saved_cents"]
    alloc_db.add_income_bulk(
        [
            {"received_on": date(2026, 9, i + 1), "amount_cents": 100000,
             "source": "Salary", "description": f"imported {i}"}
            for i in range(3)
        ]
    )
    check(
        "imported income is allocated too",
        alloc_db.get_goal(trip)["saved_cents"] == before + 3 * 5000,
        str(alloc_db.get_goal(trip)["saved_cents"]),
    )

    # The goals page should surface a plan that claims more than comes in.
    alloc_db.update_goal(trip, "Trip", 200000, allocation_pct=95)
    check("over-allocation is detectable", alloc_db.total_allocation_pct() > 100,
          str(alloc_db.total_allocation_pct()))
    check("median income is available for the hint", alloc_db.typical_income() == 100000,
          str(alloc_db.typical_income()))

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
