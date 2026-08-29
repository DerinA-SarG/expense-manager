"""Expenses page: the log, plus adding and editing entries."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from .. import csvio
from ..dialogs import CategoryManagerDialog, ExpenseDialog
from ..import_dialog import ImportDialog
from ..ledger import RIGHT, Column, LedgerModel, ledger_view, pretty_date
from ..money import format_cents
from ..widgets import Card, PageHeader, debounce
from .overview import PERIODS, period_range

def _source(row, _currency="") -> str:
    if row["subscription_id"] is None:
        return "Manual"
    return row["subscription_name"] or "Subscription"


def expense_columns() -> list[Column]:
    return [
        Column("Date", lambda r, c: pretty_date(r["spent_on"]), key=lambda r: r["spent_on"]),
        Column(
            "Description",
            lambda r, c: r["description"] or "(no description)",
            key=lambda r: (r["description"] or "").lower(),
            ink=lambda r, p: None if r["description"] else p["muted"],
            tooltip=lambda r: r["notes"],
            stretch=True,
        ),
        Column("Category", lambda r, c: r["category"], key=lambda r: r["category"].lower()),
        Column(
            "Source",
            _source,
            # Manual rows sort as one block, subscription rows as another.
            key=lambda r: ("1" if r["subscription_id"] is not None else "0") + _source(r).lower(),
            ink=lambda r, p: p["accent"] if r["subscription_id"] is not None else p["muted"],
            tooltip=lambda r: (
                "Posted automatically by a subscription."
                if r["subscription_id"] is not None
                else ""
            ),
        ),
        Column(
            "Amount",
            lambda r, c: format_cents(r["amount_cents"], c),
            key=lambda r: r["amount_cents"],
            align=RIGHT,
        ),
    ]


class ExpensesPage(QWidget):
    def __init__(self, db, palette: dict, on_changed=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.pal = palette
        self.on_changed = on_changed or (lambda: None)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        self.header = PageHeader("Expenses", "")
        import_button = QPushButton("Import CSV...")
        import_button.setToolTip("Load a transaction export from your bank or card issuer")
        import_button.clicked.connect(self.import_csv)
        self.header.add_action(import_button)

        self.export_button = QPushButton("Export CSV...")
        self.export_button.setToolTip("Save the rows currently shown to a CSV file")
        self.export_button.clicked.connect(self.export_csv)
        self.header.add_action(self.export_button)

        add_button = QPushButton("+  Add expense")
        add_button.setObjectName("Primary")
        add_button.clicked.connect(self.add_expense)
        self.header.add_action(add_button)
        outer.addWidget(self.header)

        # -------------------------------------------------------- filter bar
        filters = QHBoxLayout()
        filters.setSpacing(10)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search descriptions, notes, categories...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(debounce(self.search, self.refresh))
        filters.addWidget(self.search, 3)

        self.category_filter = QComboBox()
        self.category_filter.setMinimumWidth(150)
        self.category_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.category_filter, 1)

        self.period_filter = QComboBox()
        for label, key in PERIODS:
            self.period_filter.addItem(label, key)
        self.period_filter.setCurrentIndex(len(PERIODS) - 1)  # default to All time
        self.period_filter.setMinimumWidth(140)
        self.period_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.period_filter, 1)

        categories_button = QPushButton("Categories...")
        categories_button.setToolTip("Rename, merge or delete categories")
        categories_button.clicked.connect(self.manage_categories)
        filters.addWidget(categories_button)

        outer.addLayout(filters)

        # ------------------------------------------------------------- table
        card = Card(padding=0, spacing=0)
        self.model = LedgerModel(expense_columns(), self.pal)
        self.table = ledger_view(self.model, stretch=1)
        self.table.doubleClicked.connect(self.edit_selected)
        self.table.selectionModel().selectionChanged.connect(self._sync_buttons)

        card.body.addWidget(self.table)
        outer.addWidget(card, 1)

        # ------------------------------------------------------------ footer
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.summary = QLabel("")
        self.summary.setObjectName("Subtle")
        footer.addWidget(self.summary)
        footer.addStretch(1)

        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete_selected)
        footer.addWidget(self.edit_button)
        footer.addWidget(self.delete_button)
        outer.addLayout(footer)

        QShortcut(QKeySequence.StandardKey.Delete, self.table, self.delete_selected)
        QShortcut(QKeySequence("Ctrl+N"), self, self.add_expense)

        self.refresh_categories()
        self.refresh()

    # ------------------------------------------------------------------ theme

    def set_palette(self, palette: dict) -> None:
        self.pal = palette
        self.refresh()

    # ----------------------------------------------------------------- filters

    def refresh_categories(self) -> None:
        current = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("All categories", None)
        for name in self.db.categories():
            self.category_filter.addItem(name, name)
        index = self.category_filter.findData(current)
        self.category_filter.setCurrentIndex(max(index, 0))
        self.category_filter.blockSignals(False)

    # ------------------------------------------------------------------ table

    def _current_rows(self):
        start, end = period_range(self.period_filter.currentData())
        return self.db.list_expenses(
            start=start,
            end=end,
            category=self.category_filter.currentData(),
            search=self.search.text().strip() or None,
        )

    def refresh(self) -> None:
        rows = self._current_rows()
        currency = self.db.currency

        self.model.set_palette(self.pal)
        self.model.set_rows(rows, currency)

        total = sum(row["amount_cents"] for row in rows)
        noun = "expense" if len(rows) == 1 else "expenses"
        self.summary.setText(
            f"{len(rows):,} {noun} · {format_cents(total, currency)}"
            if rows
            else "Nothing matches these filters."
        )
        self.header.set_subtitle(
            "Every charge, manual or posted by a subscription. Double-click a row to edit it."
        )
        self._sync_buttons()

    def _sync_buttons(self, *_) -> None:
        count = len(self._selected_ids())
        self.edit_button.setEnabled(count == 1)
        self.delete_button.setEnabled(count >= 1)

    def _selected_ids(self) -> list[int]:
        model = self.table.selectionModel()
        ids = []
        for index in model.selectedRows() if model else []:
            row = self.model.row_at(index.row())
            if row is not None:
                ids.append(int(row["id"]))
        return ids

    # ---------------------------------------------------------------- actions

    def add_expense(self) -> None:
        dialog = ExpenseDialog(self.db.categories(), self.db.currency, parent=self)
        if dialog.exec():
            self.db.add_expense(**dialog.values())
            self.refresh_categories()
            self.refresh()
            self.on_changed()

    def edit_selected(self) -> None:
        ids = self._selected_ids()
        if len(ids) != 1:
            return
        row = self.db.conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (ids[0],)
        ).fetchone()
        if row is None:
            return
        dialog = ExpenseDialog(self.db.categories(), self.db.currency, row=row, parent=self)
        if dialog.exec():
            self.db.update_expense(ids[0], **dialog.values())
            self.refresh_categories()
            self.refresh()
            self.on_changed()

    def delete_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        noun = "expense" if len(ids) == 1 else f"{len(ids)} expenses"
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Delete")
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setText(f"Delete {noun}?")
        confirm.setInformativeText("This cannot be undone.")
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirm.exec() == QMessageBox.StandardButton.Yes:
            self.db.delete_expenses(ids)
            self.refresh()
            self.on_changed()

    # ------------------------------------------------------------ csv / admin

    def import_csv(self) -> None:
        dialog = ImportDialog(self.db, self.pal, parent=self)
        if dialog.exec() and dialog.imported:
            self.refresh_categories()
            self.refresh()
            self.on_changed()

            parts = []
            if dialog.imported_expenses:
                parts.append(
                    f"{dialog.imported_expenses:,} expense"
                    f"{'s' if dialog.imported_expenses != 1 else ''}"
                )
            if dialog.imported_income:
                parts.append(f"{dialog.imported_income:,} income entries")
            QMessageBox.information(
                self,
                "Import complete",
                " and ".join(parts) + " added. Deposits are on the Income page.",
            )

    def export_csv(self) -> None:
        rows = self._current_rows()
        if not rows:
            QMessageBox.information(
                self, "Nothing to export", "No expenses match the current filters."
            )
            return

        suggested = f"expenses-{date.today().isoformat()}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export expenses", suggested, "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            written = csvio.export_expenses(rows, path)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return

        QMessageBox.information(
            self,
            "Export complete",
            f"{written:,} expense{'s' if written != 1 else ''} written to:\n{path}\n\n"
            "This is what the current filters show, and it imports back into the "
            "app unchanged.",
        )

    def manage_categories(self) -> None:
        dialog = CategoryManagerDialog(self.db, parent=self)
        dialog.exec()
        if dialog.changed:
            self.refresh_categories()
            self.refresh()
            self.on_changed()
