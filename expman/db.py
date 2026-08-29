"""SQLite storage.

Everything lives in one file under the per-user data directory, so a backup is a
file copy and there is no server, no migration tooling and no account.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

from .recurrence import advance

SCHEMA_VERSION = "2"

DEFAULT_CATEGORIES = [
    "Groceries",
    "Dining",
    "Rent & Housing",
    "Utilities",
    "Transport",
    "Subscriptions",
    "Health",
    "Shopping",
    "Entertainment",
    "Other",
]

DEFAULT_INCOME_SOURCES = [
    "Salary",
    "Freelance",
    "Interest",
    "Refund",
    "Gift",
    "Transfer in",
    "Other",
]

DEFAULT_SETTINGS = {
    "schema_version": SCHEMA_VERSION,
    "currency_symbol": "$",
    "theme": "dark",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    amount_cents INTEGER NOT NULL,
    category     TEXT    NOT NULL DEFAULT 'Subscriptions',
    cycle        TEXT    NOT NULL,
    start_date   TEXT    NOT NULL,
    next_due     TEXT    NOT NULL,
    active       INTEGER NOT NULL DEFAULT 1,
    notes        TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS expenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    spent_on        TEXT    NOT NULL,
    amount_cents    INTEGER NOT NULL,
    category        TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    notes           TEXT    NOT NULL DEFAULT '',
    subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE SET NULL,
    created_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_expenses_spent_on ON expenses(spent_on);
CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category);

CREATE TABLE IF NOT EXISTS income_sources (
    name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS income (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    received_on  TEXT    NOT NULL,
    amount_cents INTEGER NOT NULL,
    source       TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    notes        TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_income_received_on ON income(received_on);

CREATE TABLE IF NOT EXISTS goals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    target_cents   INTEGER NOT NULL,
    -- Share of every income entry that is set aside for this goal, 0 for none.
    allocation_pct REAL    NOT NULL DEFAULT 0,
    notes          TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL
);

"""

# Kept apart from the script above because an old database has to have this
# table rebuilt around its constraints, and a second copy of the definition
# would be one refresh away from disagreeing with this one.
_CONTRIBUTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS {name} (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id      INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    made_on      TEXT    NOT NULL,
    amount_cents INTEGER NOT NULL,
    note         TEXT    NOT NULL DEFAULT '',
    -- Set when this was carved out of an income entry automatically. Deleting
    -- that income takes the contribution with it, so the two never disagree.
    income_id    INTEGER REFERENCES income(id) ON DELETE CASCADE,
    -- The goal's percentage at the moment this was set aside. Kept on the row
    -- rather than read back off the goal, so that later changing the goal's
    -- share cannot reach back and restate money already put away.
    allocation_pct REAL NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL
);
"""

_SCHEMA += _CONTRIBUTIONS_TABLE.format(name="goal_contributions")

# A subscription back-dated by years would otherwise post thousands of rows.
_MAX_CATCHUP_POSTINGS = 520


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    path = Path(base) / "ExpenseManager"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _as_iso(value) -> str:
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value)


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_data_dir() / "expenses.db"
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self._seed()

    def _migrate(self) -> None:
        """Add columns that CREATE TABLE IF NOT EXISTS cannot add to an existing
        table. Each is harmless to re-run, so there is no version bookkeeping."""
        additions = (
            ("goals", "allocation_pct", "REAL NOT NULL DEFAULT 0"),
            ("goal_contributions", "income_id", "INTEGER REFERENCES income(id)"),
            ("goal_contributions", "allocation_pct", "REAL NOT NULL DEFAULT 0"),
        )
        for table, column, spec in additions:
            existing = {
                row["name"]
                for row in self.conn.execute(f"PRAGMA table_info({table})")
            }
            if column not in existing:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {spec}")

        self._cascade_contributions_from_income()

        # Indexed here rather than in the schema script, which runs before the
        # column above exists on a database created by an earlier version -- and
        # after the rebuild above, which takes the old table's indexes with it.
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_contributions_goal "
            "ON goal_contributions(goal_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_contributions_income "
            "ON goal_contributions(income_id)"
        )
        # _seed only ever inserts, so a database carried forward from an older
        # build would otherwise keep reporting the version it was created at.
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SCHEMA_VERSION,),
        )
        self.conn.commit()

    def _cascade_contributions_from_income(self) -> None:
        """Give goal_contributions.income_id the cascade it was declared with.

        The column arrives by ALTER TABLE on every database created before goals
        could take a share of income, and ALTER TABLE ADD COLUMN cannot carry a
        cascade with it. What is left is a reference that is enforced but never
        acts: with foreign keys on, deleting an income entry that fed a goal
        fails on the constraint instead of taking its contributions with it, and
        from the income page the delete looks like it simply did nothing.

        SQLite cannot alter a constraint, so the table is rebuilt around it.
        """
        income_fk = next(
            (
                row
                for row in self.conn.execute(
                    "PRAGMA foreign_key_list(goal_contributions)"
                )
                if row["table"] == "income"
            ),
            None,
        )
        if income_fk is not None and income_fk["on_delete"] == "CASCADE":
            return

        # The pragma is ignored inside a transaction, and the swap would trip
        # the very constraint being repaired while rows still point at the old
        # table. Both mean the rebuild has to start from a clean connection.
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = OFF")
        try:
            self.conn.execute(
                _CONTRIBUTIONS_TABLE.format(name="goal_contributions_new")
            )
            # A contribution can only outlive its income on a database where the
            # reference went unenforced. The cascade it should always have had is
            # applied to it here rather than leaving a row nothing can explain.
            self.conn.execute(
                "INSERT INTO goal_contributions_new "
                "(id, goal_id, made_on, amount_cents, note, income_id, "
                " allocation_pct, created_at) "
                "SELECT id, goal_id, made_on, amount_cents, note, income_id, "
                "       allocation_pct, created_at FROM goal_contributions "
                " WHERE income_id IS NULL OR income_id IN (SELECT id FROM income)"
            )
            self.conn.execute("DROP TABLE goal_contributions")
            self.conn.execute(
                "ALTER TABLE goal_contributions_new RENAME TO goal_contributions"
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            self.conn.execute("PRAGMA foreign_keys = ON")

    def _seed(self) -> None:
        for key, value in DEFAULT_SETTINGS.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (key, value)
            )
        self.conn.executemany(
            "INSERT OR IGNORE INTO categories (name) VALUES (?)",
            [(c,) for c in DEFAULT_CATEGORIES],
        )
        self.conn.executemany(
            "INSERT OR IGNORE INTO income_sources (name) VALUES (?)",
            [(s,) for s in DEFAULT_INCOME_SOURCES],
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- settings

    def get_setting(self, key: str, fallback: str = "") -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else fallback

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    @property
    def currency(self) -> str:
        return self.get_setting("currency_symbol", "$")

    # -------------------------------------------------------------- categories

    def categories(self) -> list[str]:
        rows = self.conn.execute("SELECT name FROM categories ORDER BY name COLLATE NOCASE")
        return [r["name"] for r in rows]

    def ensure_category(self, name: str, commit: bool = True) -> str:
        name = (name or "").strip() or "Other"
        self.conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
        if commit:
            self.conn.commit()
        return name

    # ---------------------------------------------------------------- expenses

    def add_expense(
        self,
        spent_on,
        amount_cents: int,
        category: str,
        description: str = "",
        notes: str = "",
        subscription_id: int | None = None,
        commit: bool = True,
    ) -> int:
        category = self.ensure_category(category, commit=commit)
        cur = self.conn.execute(
            "INSERT INTO expenses "
            "(spent_on, amount_cents, category, description, notes, subscription_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                _as_iso(spent_on),
                int(amount_cents),
                category,
                description.strip(),
                notes.strip(),
                subscription_id,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        if commit:
            self.conn.commit()
        return int(cur.lastrowid)

    def update_expense(
        self,
        expense_id: int,
        spent_on,
        amount_cents: int,
        category: str,
        description: str = "",
        notes: str = "",
    ) -> None:
        category = self.ensure_category(category)
        self.conn.execute(
            "UPDATE expenses SET spent_on = ?, amount_cents = ?, category = ?, "
            "description = ?, notes = ? WHERE id = ?",
            (
                _as_iso(spent_on),
                int(amount_cents),
                category,
                description.strip(),
                notes.strip(),
                int(expense_id),
            ),
        )
        self.conn.commit()

    def delete_expenses(self, ids) -> int:
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        cur = self.conn.execute("DELETE FROM expenses WHERE id IN (" + marks + ")", ids)
        self.conn.commit()
        return cur.rowcount

    def list_expenses(
        self,
        start=None,
        end=None,
        category: str | None = None,
        search: str | None = None,
    ) -> list[sqlite3.Row]:
        sql = [
            "SELECT e.*, s.name AS subscription_name FROM expenses e "
            "LEFT JOIN subscriptions s ON s.id = e.subscription_id WHERE 1 = 1"
        ]
        args: list = []
        if start:
            sql.append("AND e.spent_on >= ?")
            args.append(_as_iso(start))
        if end:
            sql.append("AND e.spent_on <= ?")
            args.append(_as_iso(end))
        if category:
            sql.append("AND e.category = ?")
            args.append(category)
        if search:
            sql.append("AND (e.description LIKE ? OR e.notes LIKE ? OR e.category LIKE ?)")
            like = "%" + search + "%"
            args += [like, like, like]
        sql.append("ORDER BY e.spent_on DESC, e.id DESC")
        return list(self.conn.execute(" ".join(sql), args))

    def category_totals(self, start=None, end=None) -> list[tuple[str, int]]:
        sql = ["SELECT category, SUM(amount_cents) AS total FROM expenses WHERE 1 = 1"]
        args: list = []
        if start:
            sql.append("AND spent_on >= ?")
            args.append(_as_iso(start))
        if end:
            sql.append("AND spent_on <= ?")
            args.append(_as_iso(end))
        sql.append("GROUP BY category HAVING total > 0 ORDER BY total DESC")
        rows = self.conn.execute(" ".join(sql), args)
        return [(r["category"], int(r["total"])) for r in rows]

    def expense_span(self) -> tuple[date, date] | None:
        row = self.conn.execute(
            "SELECT MIN(spent_on) AS lo, MAX(spent_on) AS hi FROM expenses"
        ).fetchone()
        if not row or not row["lo"]:
            return None
        return date.fromisoformat(row["lo"]), date.fromisoformat(row["hi"])

    # ----------------------------------------------------------- subscriptions

    def add_subscription(
        self,
        name: str,
        amount_cents: int,
        category: str,
        cycle: str,
        start_date,
        next_due=None,
        active: bool = True,
        notes: str = "",
    ) -> int:
        category = self.ensure_category(category)
        # The schedule is the start date plus the cycle, nothing else. Pointing
        # the cursor at the start date means a back-dated subscription posts the
        # charges it has already run up instead of quietly losing them.
        if next_due is None:
            next_due = start_date
        cur = self.conn.execute(
            "INSERT INTO subscriptions "
            "(name, amount_cents, category, cycle, start_date, next_due, active, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name.strip(),
                int(amount_cents),
                category,
                cycle,
                _as_iso(start_date),
                _as_iso(next_due),
                int(bool(active)),
                notes.strip(),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_subscription(
        self,
        sub_id: int,
        name: str,
        amount_cents: int,
        category: str,
        cycle: str,
        start_date,
        next_due=None,
        active: bool = True,
        notes: str = "",
    ) -> None:
        category = self.ensure_category(category)
        if next_due is None:
            next_due = self._posting_cursor(sub_id, _as_date(start_date), cycle)
        self.conn.execute(
            "UPDATE subscriptions SET name = ?, amount_cents = ?, category = ?, cycle = ?, "
            "start_date = ?, next_due = ?, active = ?, notes = ? WHERE id = ?",
            (
                name.strip(),
                int(amount_cents),
                category,
                cycle,
                _as_iso(start_date),
                _as_iso(next_due),
                int(bool(active)),
                notes.strip(),
                int(sub_id),
            ),
        )
        self.conn.commit()

    def _posting_cursor(self, sub_id: int, start_date: date, cycle: str) -> date:
        """The first charge on this schedule that is not in the expense log yet.

        Editing a subscription can move its start date or change its cycle, which
        re-cuts every future billing date. Walking the new schedule forward past
        the last charge already posted lands on the next genuinely unposted one,
        so a re-scheduled subscription neither doubles up nor skips ahead.
        """
        row = self.conn.execute(
            "SELECT MAX(spent_on) AS last FROM expenses WHERE subscription_id = ?",
            (int(sub_id),),
        ).fetchone()
        last = row["last"] if row else None
        if not last:
            return start_date

        # Clear the whole period the last charge paid for, not merely its date.
        # Moving a subscription from the 18th to the 20th re-cuts the schedule
        # but does not buy another month, so the next charge is due in
        # September -- landing on the 20th would bill August twice.
        floor = advance(date.fromisoformat(last), cycle, start_date.day)
        due = start_date
        steps = 0
        while due < floor and steps < _MAX_CATCHUP_POSTINGS:
            due = advance(due, cycle, start_date.day)
            steps += 1
        return due

    def set_subscription_active(self, sub_id: int, active: bool) -> None:
        self.conn.execute(
            "UPDATE subscriptions SET active = ? WHERE id = ?",
            (int(bool(active)), int(sub_id)),
        )
        self.conn.commit()

    def delete_subscription(self, sub_id: int, drop_posted: bool = False) -> None:
        """Remove a subscription.

        Charges it already posted are real history, so by default they are kept
        and simply orphaned rather than deleted along with it.
        """
        if drop_posted:
            self.conn.execute("DELETE FROM expenses WHERE subscription_id = ?", (int(sub_id),))
        self.conn.execute("DELETE FROM subscriptions WHERE id = ?", (int(sub_id),))
        self.conn.commit()

    def list_subscriptions(self, active_only: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM subscriptions"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY active DESC, next_due ASC, name COLLATE NOCASE"
        return list(self.conn.execute(sql))

    def get_subscription(self, sub_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM subscriptions WHERE id = ?", (int(sub_id),)
        ).fetchone()

    def posted_count(self, sub_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM expenses WHERE subscription_id = ?", (int(sub_id),)
        ).fetchone()
        return int(row["n"])

    def post_due_subscriptions(self, today: date | None = None) -> int:
        """Turn every subscription charge that has come due into a real expense.

        ``next_due`` is advanced past today and persisted, so calling this on
        every launch is idempotent -- a charge is never posted twice.
        """
        today = today or date.today()
        posted = 0
        for sub in self.list_subscriptions(active_only=True):
            due = date.fromisoformat(sub["next_due"])
            anchor = date.fromisoformat(sub["start_date"]).day
            moved = False
            steps = 0
            while due <= today and steps < _MAX_CATCHUP_POSTINGS:
                self.add_expense(
                    spent_on=due,
                    amount_cents=sub["amount_cents"],
                    category=sub["category"],
                    description=sub["name"],
                    subscription_id=sub["id"],
                    commit=False,
                )
                due = advance(due, sub["cycle"], anchor)
                posted += 1
                steps += 1
                moved = True
            if moved:
                self.conn.execute(
                    "UPDATE subscriptions SET next_due = ? WHERE id = ?",
                    (due.isoformat(), sub["id"]),
                )
        if posted:
            self.conn.commit()
        return posted

    # ------------------------------------------------------ category management

    def category_usage(self) -> list[dict]:
        """Every category with the counts that decide whether it can be deleted."""
        sql = """
            SELECT c.name AS name,
                   (SELECT COUNT(*) FROM expenses e
                     WHERE e.category = c.name)               AS expenses,
                   (SELECT COALESCE(SUM(e.amount_cents), 0) FROM expenses e
                     WHERE e.category = c.name)               AS total_cents,
                   (SELECT COUNT(*) FROM subscriptions s
                     WHERE s.category = c.name)               AS subscriptions
              FROM categories c
             ORDER BY c.name COLLATE NOCASE
        """
        return [dict(r) for r in self.conn.execute(sql)]

    def rename_category(self, old: str, new: str) -> str:
        """Rename a category, or fold it into an existing one.

        Renaming onto a name that already exists is a merge -- that is the
        natural way to fix a typo that has been in use for a while, or to decide
        two categories should always have been one.
        """
        new = (new or "").strip()
        if not new:
            raise ValueError("Category name cannot be empty.")
        if new == old:
            return new

        with self.conn:  # one transaction; a half-done rename would strand rows
            self.conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (new,))
            self.conn.execute(
                "UPDATE expenses SET category = ? WHERE category = ?", (new, old)
            )
            self.conn.execute(
                "UPDATE subscriptions SET category = ? WHERE category = ?", (new, old)
            )
            self.conn.execute("DELETE FROM categories WHERE name = ?", (old,))
        return new

    def delete_category(self, name: str) -> None:
        """Remove an unused category. Anything still referencing it is a merge."""
        usage = next((u for u in self.category_usage() if u["name"] == name), None)
        if usage is None:
            return
        if usage["expenses"] or usage["subscriptions"]:
            raise ValueError(
                f"'{name}' is still used by {usage['expenses']} expense(s) and "
                f"{usage['subscriptions']} subscription(s). Merge it into another "
                "category instead."
            )
        with self.conn:
            self.conn.execute("DELETE FROM categories WHERE name = ?", (name,))

    # ------------------------------------------------------------------ import

    def fingerprints(self) -> set[tuple[str, int, str]]:
        """Keys for duplicate detection on import.

        Statement exports routinely overlap, so re-importing last month's file
        alongside this one must not double-count anything.
        """
        rows = self.conn.execute(
            "SELECT spent_on, amount_cents, description FROM expenses"
        )
        return {
            (r["spent_on"], int(r["amount_cents"]), (r["description"] or "").strip().lower())
            for r in rows
        }

    def add_expenses_bulk(self, records) -> int:
        """Insert many expenses in one transaction. Each record is a dict."""
        count = 0
        for rec in records:
            self.add_expense(
                spent_on=rec["spent_on"],
                amount_cents=rec["amount_cents"],
                category=rec.get("category", "Other"),
                description=rec.get("description", ""),
                notes=rec.get("notes", ""),
                commit=False,
            )
            count += 1
        if count:
            self.conn.commit()
        return count

    # ------------------------------------------------------------------ income

    def income_sources(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM income_sources ORDER BY name COLLATE NOCASE"
        )
        return [r["name"] for r in rows]

    def ensure_income_source(self, name: str, commit: bool = True) -> str:
        name = (name or "").strip() or "Other"
        self.conn.execute("INSERT OR IGNORE INTO income_sources (name) VALUES (?)", (name,))
        if commit:
            self.conn.commit()
        return name

    def add_income(
        self,
        received_on,
        amount_cents: int,
        source: str,
        description: str = "",
        notes: str = "",
        commit: bool = True,
        allocate: bool = True,
    ) -> int:
        source = self.ensure_income_source(source, commit=commit)
        cur = self.conn.execute(
            "INSERT INTO income "
            "(received_on, amount_cents, source, description, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                _as_iso(received_on),
                int(amount_cents),
                source,
                description.strip(),
                notes.strip(),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        income_id = int(cur.lastrowid)
        # Done here rather than at each call site, so no path -- manual entry,
        # CSV import, anything later -- can forget to set money aside.
        if allocate:
            self.allocate_income(income_id, commit=False)
        if commit:
            self.conn.commit()
        return income_id

    def update_income(
        self,
        income_id: int,
        received_on,
        amount_cents: int,
        source: str,
        description: str = "",
        notes: str = "",
    ) -> None:
        source = self.ensure_income_source(source)
        self.conn.execute(
            "UPDATE income SET received_on = ?, amount_cents = ?, source = ?, "
            "description = ?, notes = ? WHERE id = ?",
            (
                _as_iso(received_on),
                int(amount_cents),
                source,
                description.strip(),
                notes.strip(),
                int(income_id),
            ),
        )
        # The amount may have changed, so the shares taken from it must be redone.
        self.allocate_income(income_id, commit=False)
        self.conn.commit()

    def delete_income(self, ids) -> int:
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        cur = self.conn.execute("DELETE FROM income WHERE id IN (" + marks + ")", ids)
        self.conn.commit()
        return cur.rowcount

    def list_income(
        self, start=None, end=None, source: str | None = None, search: str | None = None
    ) -> list[sqlite3.Row]:
        sql = ["SELECT * FROM income WHERE 1 = 1"]
        args: list = []
        if start:
            sql.append("AND received_on >= ?")
            args.append(_as_iso(start))
        if end:
            sql.append("AND received_on <= ?")
            args.append(_as_iso(end))
        if source:
            sql.append("AND source = ?")
            args.append(source)
        if search:
            sql.append("AND (description LIKE ? OR notes LIKE ? OR source LIKE ?)")
            like = "%" + search + "%"
            args += [like, like, like]
        sql.append("ORDER BY received_on DESC, id DESC")
        return list(self.conn.execute(" ".join(sql), args))

    def income_total(self, start=None, end=None) -> int:
        sql = ["SELECT COALESCE(SUM(amount_cents), 0) AS total FROM income WHERE 1 = 1"]
        args: list = []
        if start:
            sql.append("AND received_on >= ?")
            args.append(_as_iso(start))
        if end:
            sql.append("AND received_on <= ?")
            args.append(_as_iso(end))
        return int(self.conn.execute(" ".join(sql), args).fetchone()["total"])

    def income_by_source(self, start=None, end=None) -> list[tuple[str, int]]:
        sql = ["SELECT source, SUM(amount_cents) AS total FROM income WHERE 1 = 1"]
        args: list = []
        if start:
            sql.append("AND received_on >= ?")
            args.append(_as_iso(start))
        if end:
            sql.append("AND received_on <= ?")
            args.append(_as_iso(end))
        sql.append("GROUP BY source HAVING total > 0 ORDER BY total DESC")
        rows = self.conn.execute(" ".join(sql), args)
        return [(r["source"], int(r["total"])) for r in rows]

    def income_span(self) -> tuple[date, date] | None:
        row = self.conn.execute(
            "SELECT MIN(received_on) AS lo, MAX(received_on) AS hi FROM income"
        ).fetchone()
        if not row or not row["lo"]:
            return None
        return date.fromisoformat(row["lo"]), date.fromisoformat(row["hi"])

    def income_fingerprints(self) -> set[tuple[str, int, str]]:
        rows = self.conn.execute(
            "SELECT received_on, amount_cents, description FROM income"
        )
        return {
            (r["received_on"], int(r["amount_cents"]), (r["description"] or "").strip().lower())
            for r in rows
        }

    def add_income_bulk(self, records) -> int:
        count = 0
        for rec in records:
            self.add_income(
                received_on=rec["received_on"],
                amount_cents=rec["amount_cents"],
                source=rec.get("source", "Other"),
                description=rec.get("description", ""),
                notes=rec.get("notes", ""),
                commit=False,
            )
            count += 1
        if count:
            self.conn.commit()
        return count

    # ------------------------------------------------------------------- goals

    # ------------------------------------------------------------------- wipe

    # What each switch on the "delete everything" dialog actually clears. Order
    # matters: expenses reference subscriptions, contributions reference goals.
    WIPEABLE = {
        "expenses": ("Expenses", ("expenses",)),
        "income": ("Income", ("income",)),
        "subscriptions": ("Subscriptions", ("expenses_from_subs", "subscriptions")),
        "goals": ("Goals and contributions", ("goal_contributions", "goals")),
        "categories": ("Custom categories and sources", ("categories", "income_sources")),
    }

    def counts(self) -> dict[str, int]:
        """How much of each kind of record exists, for the delete confirmation."""
        query = {
            "expenses": "SELECT COUNT(*) FROM expenses",
            "income": "SELECT COUNT(*) FROM income",
            "subscriptions": "SELECT COUNT(*) FROM subscriptions",
            "goals": "SELECT COUNT(*) FROM goals",
            "categories": "SELECT COUNT(*) FROM categories",
        }
        return {key: int(self.conn.execute(sql).fetchone()[0]) for key, sql in query.items()}

    def wipe(self, kinds) -> dict[str, int]:
        """Delete whole classes of record. Returns how many rows each removed.

        Categories are reseeded rather than left empty, so the app is usable
        straight afterwards instead of starting with an empty dropdown.
        """
        kinds = [k for k in kinds if k in self.WIPEABLE]
        removed: dict[str, int] = {}

        with self.conn:
            for kind in kinds:
                if kind == "subscriptions":
                    # Charges a subscription posted are its own doing; clearing
                    # subscriptions takes them with it, which is what "delete my
                    # subscriptions" means to someone starting over.
                    cur = self.conn.execute(
                        "DELETE FROM expenses WHERE subscription_id IS NOT NULL"
                    )
                    removed["posted charges"] = cur.rowcount
                    cur = self.conn.execute("DELETE FROM subscriptions")
                    removed["subscriptions"] = cur.rowcount
                elif kind == "goals":
                    cur = self.conn.execute("DELETE FROM goal_contributions")
                    removed["contributions"] = cur.rowcount
                    cur = self.conn.execute("DELETE FROM goals")
                    removed["goals"] = cur.rowcount
                elif kind == "categories":
                    cur = self.conn.execute("DELETE FROM categories")
                    removed["categories"] = cur.rowcount
                    self.conn.execute("DELETE FROM income_sources")
                else:
                    cur = self.conn.execute(f"DELETE FROM {kind}")
                    removed[kind] = cur.rowcount

        if "categories" in kinds:
            self._seed()
        self.conn.execute("VACUUM")
        return {k: v for k, v in removed.items() if v}

    def backup_to(self, directory=None) -> Path:
        """Copy the database file, with the WAL folded in, to a timestamped file."""
        import shutil

        # Checkpoint first, or recent writes still living in the -wal file would
        # be missing from the copy.
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        target_dir = Path(directory) if directory else self.path.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = target_dir / f"{self.path.stem}-backup-{stamp}.db"
        shutil.copy2(self.path, target)
        return target

    # ------------------------------------------------------------------- goals

    def add_goal(
        self, name: str, target_cents: int, allocation_pct: float = 0.0, notes: str = ""
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO goals (name, target_cents, allocation_pct, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                name.strip(),
                int(target_cents),
                float(allocation_pct),
                notes.strip(),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_goal(
        self,
        goal_id: int,
        name: str,
        target_cents: int,
        allocation_pct: float = 0.0,
        notes: str = "",
    ) -> None:
        self.conn.execute(
            "UPDATE goals SET name = ?, target_cents = ?, allocation_pct = ?, notes = ? "
            "WHERE id = ?",
            (
                name.strip(),
                int(target_cents),
                float(allocation_pct),
                notes.strip(),
                int(goal_id),
            ),
        )
        self.conn.commit()

    def delete_goal(self, goal_id: int) -> None:
        """Contributions cascade away with the goal -- they have no meaning
        without it, unlike a subscription's posted charges, which were real
        spending in their own right."""
        self.conn.execute("DELETE FROM goals WHERE id = ?", (int(goal_id),))
        self.conn.commit()

    def goals(self) -> list[dict]:
        """Every goal with what has been put into it so far."""
        sql = """
            SELECT g.id, g.name, g.target_cents, g.allocation_pct, g.notes,
                   COALESCE((SELECT SUM(c.amount_cents) FROM goal_contributions c
                              WHERE c.goal_id = g.id), 0) AS saved_cents,
                   (SELECT COUNT(*) FROM goal_contributions c
                     WHERE c.goal_id = g.id)               AS contributions,
                   COALESCE((SELECT SUM(c.amount_cents) FROM goal_contributions c
                              WHERE c.goal_id = g.id
                                AND c.income_id IS NOT NULL), 0) AS from_income_cents
              FROM goals g
             ORDER BY g.name COLLATE NOCASE
        """
        return [dict(r) for r in self.conn.execute(sql)]

    def typical_income(self) -> int:
        """The middle income entry by size, for showing what a share works out to.

        The median rather than the mean: one large one-off would otherwise make
        every percentage look more generous than it is.
        """
        amounts = [
            int(r["amount_cents"])
            for r in self.conn.execute(
                "SELECT amount_cents FROM income ORDER BY amount_cents"
            )
        ]
        if not amounts:
            return 0
        return amounts[len(amounts) // 2]

    def total_allocation_pct(self) -> float:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(allocation_pct), 0) AS total FROM goals"
        ).fetchone()
        return float(row["total"])

    def get_goal(self, goal_id: int) -> dict | None:
        return next((g for g in self.goals() if g["id"] == int(goal_id)), None)

    def add_contribution(
        self,
        goal_id: int,
        made_on,
        amount_cents: int,
        note: str = "",
        income_id: int | None = None,
        allocation_pct: float = 0.0,
        commit: bool = True,
    ) -> int:
        """Record money moved into (or, with a negative amount, back out of) a goal."""
        cur = self.conn.execute(
            "INSERT INTO goal_contributions "
            "(goal_id, made_on, amount_cents, note, income_id, allocation_pct, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                int(goal_id),
                _as_iso(made_on),
                int(amount_cents),
                note.strip(),
                income_id,
                float(allocation_pct),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        if commit:
            self.conn.commit()
        return int(cur.lastrowid)

    # ------------------------------------------ setting money aside from income

    def _allocation_note(self, pct: float, income_row) -> str:
        label = income_row["description"] or income_row["source"]
        return f"{pct:g}% of {label}"

    def allocate_income(self, income_id: int, commit: bool = True) -> int:
        """Carve each goal's share out of one income entry.

        Any earlier automatic split of the same entry is cleared first, so
        re-running this after an edit corrects the amounts instead of doubling
        them. An entry that has been split before is re-cut at the rates it was
        split at originally, not at whatever the goals say today: editing a
        payslip is a correction to that payslip, and should not quietly restate
        money set aside months ago under a share that has since changed.
        """
        row = self.conn.execute(
            "SELECT * FROM income WHERE id = ?", (int(income_id),)
        ).fetchone()
        if row is None:
            return 0

        prior = {
            int(r["goal_id"]): float(r["allocation_pct"])
            for r in self.conn.execute(
                "SELECT goal_id, allocation_pct FROM goal_contributions "
                "WHERE income_id = ?",
                (int(income_id),),
            )
        }
        self.conn.execute(
            "DELETE FROM goal_contributions WHERE income_id = ?", (int(income_id),)
        )

        made = 0
        goals = self.conn.execute(
            "SELECT id, name, allocation_pct FROM goals "
            "WHERE allocation_pct > 0 OR id IN (%s)"
            % (",".join("?" * len(prior)) or "NULL"),
            tuple(prior),
        ).fetchall()
        for goal in goals:
            pct = prior.get(int(goal["id"]), float(goal["allocation_pct"]))
            share = round(row["amount_cents"] * pct / 100)
            if share <= 0:
                continue
            self.add_contribution(
                goal["id"],
                row["received_on"],
                share,
                note=self._allocation_note(pct, row),
                income_id=int(income_id),
                allocation_pct=pct,
                commit=False,
            )
            made += 1
        if commit:
            self.conn.commit()
        return made

    def list_contributions(self, goal_id: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM goal_contributions WHERE goal_id = ? "
                "ORDER BY made_on DESC, id DESC",
                (int(goal_id),),
            )
        )

    def delete_contributions(self, ids) -> int:
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        cur = self.conn.execute(
            "DELETE FROM goal_contributions WHERE id IN (" + marks + ")", ids
        )
        self.conn.commit()
        return cur.rowcount
