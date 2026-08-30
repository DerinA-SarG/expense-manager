"""Income page: money in, logged the same way expenses are."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..dialogs import IncomeDialog
from ..ledger import (
    RIGHT,
    Column,
    LedgerModel,
    is_hidden,
    ledger_view,
    pretty_date,
)
from ..money import format_cents
from ..widgets import Card, EmptyState, PageHeader, StatCard, debounce
from .overview import PERIODS, period_range

def shown_column() -> Column:
    """The tick box that keeps a row in this page's figures."""
    return Column(
        "Shown",
        lambda r, c: "",
        key=lambda r: 0 if is_hidden(r) else 1,
        align=int(Qt.AlignmentFlag.AlignCenter),
        checkable=True,
    )


def income_columns() -> list[Column]:
    return [
        shown_column(),
        Column("Date", lambda r, c: pretty_date(r["received_on"]), key=lambda r: r["received_on"]),
        Column(
            "Description",
            lambda r, c: r["description"] or "(no description)",
            key=lambda r: (r["description"] or "").lower(),
            ink=lambda r, p: None if r["description"] else p["muted"],
            tooltip=lambda r: r["notes"],
            stretch=True,
        ),
        Column("Source", lambda r, c: r["source"], key=lambda r: r["source"].lower()),
        Column(
            "Amount",
            lambda r, c: format_cents(r["amount_cents"], c),
            key=lambda r: r["amount_cents"],
            align=RIGHT,
            ink=lambda r, p: p["good"],
        ),
    ]


class IncomePage(QWidget):
    def __init__(self, db, palette: dict, on_changed=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.pal = palette
        self.on_changed = on_changed or (lambda: None)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        self.header = PageHeader("Income", "")
        add_button = QPushButton("+  Add income")
        add_button.setObjectName("Primary")
        add_button.clicked.connect(self.add_income)
        self.header.add_action(add_button)
        outer.addWidget(self.header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.stat_total = StatCard("Total income")
        self.stat_net = StatCard("Net")
        self.stat_top = StatCard("Biggest source")
        for card in (self.stat_total, self.stat_net, self.stat_top):
            stats.addWidget(card)
        outer.addLayout(stats)

        filters = QHBoxLayout()
        filters.setSpacing(10)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search descriptions, notes, sources...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(debounce(self.search, self.refresh))
        filters.addWidget(self.search, 3)

        self.source_filter = QComboBox()
        self.source_filter.setMinimumWidth(150)
        self.source_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.source_filter, 1)

        self.period_filter = QComboBox()
        for label, key in PERIODS:
            self.period_filter.addItem(label, key)
        self.period_filter.setCurrentIndex(len(PERIODS) - 1)
        self.period_filter.setMinimumWidth(140)
        self.period_filter.currentIndexChanged.connect(self.refresh)
        filters.addWidget(self.period_filter, 1)
        outer.addLayout(filters)

        card = Card(padding=0, spacing=0)
        self.model = LedgerModel(
            income_columns(), self.pal, on_toggle=self._set_shown
        )
        self.table = ledger_view(self.model, stretch=2, sort=1)
        self.table.doubleClicked.connect(self.edit_selected)
        self.table.selectionModel().selectionChanged.connect(self._sync_buttons)

        self.empty = EmptyState(
            "No income logged yet",
            "Add what you earn here, or import a bank statement -- deposits in a "
            "CSV are brought in as income automatically.",
        )
        first = QPushButton("Add your first income")
        first.setObjectName("Primary")
        first.clicked.connect(self.add_income)
        self.empty.add_action(first)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Transparent")
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        card.body.addWidget(self.stack)
        outer.addWidget(card, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.summary = QLabel("")
        self.summary.setObjectName("Subtle")
        footer.addWidget(self.summary)
        footer.addStretch(1)
        self.show_all_button = QPushButton("Show all")
        self.show_all_button.setToolTip(
            "Count every row the filters are showing"
        )
        self.show_all_button.clicked.connect(lambda: self._set_all_shown(True))
        self.hide_all_button = QPushButton("Hide all")
        self.hide_all_button.setToolTip(
            "Leave every row the filters are showing out of the figures"
        )
        self.hide_all_button.clicked.connect(lambda: self._set_all_shown(False))
        footer.addWidget(self.show_all_button)
        footer.addWidget(self.hide_all_button)

        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete_selected)
        footer.addWidget(self.edit_button)
        footer.addWidget(self.delete_button)
        outer.addLayout(footer)

        QShortcut(QKeySequence.StandardKey.Delete, self.table, self.delete_selected)

        self.refresh_sources()
        self.refresh()

    # ------------------------------------------------------------------ theme

    def set_palette(self, palette: dict) -> None:
        self.pal = palette
        self.empty.set_palette(palette)
        self.refresh()

    def refresh_sources(self) -> None:
        current = self.source_filter.currentData()
        self.source_filter.blockSignals(True)
        self.source_filter.clear()
        self.source_filter.addItem("All sources", None)
        for name in self.db.income_sources():
            self.source_filter.addItem(name, name)
        index = self.source_filter.findData(current)
        self.source_filter.setCurrentIndex(max(index, 0))
        self.source_filter.blockSignals(False)

    # ----------------------------------------------------------------- render

    def _current_rows(self):
        start, end = period_range(self.period_filter.currentData())
        return self.db.list_income(
            start=start,
            end=end,
            source=self.source_filter.currentData(),
            search=self.search.text().strip() or None,
        )

    def refresh(self) -> None:
        rows = self._current_rows()
        currency = self.db.currency
        start, end = period_range(self.period_filter.currentData())

        self.model.set_palette(self.pal)
        self.model.set_rows(rows, currency)

        self.stack.setCurrentIndex(0 if rows else 1)

        # Headline figures describe the chosen period rather than the filters,
        # and skip anything ticked out of the figures on either ledger. That is
        # the one place they part company with the Overview, which counts
        # everything regardless of what has been hidden here.
        income = self.db.income_total(start, end, include_hidden=False)
        spent = sum(
            a for _, a in self.db.category_totals(start, end, include_hidden=False)
        )
        net = income - spent

        self.stat_total.set(format_cents(income, currency), self._period_label())
        self.stat_net.set(
            format_cents(net, currency),
            "kept" if net >= 0 else "spent beyond income",
        )
        self.stat_net.value.setStyleSheet(
            f"color: {self.pal['good'] if net >= 0 else self.pal['critical']};"
        )

        by_source = self.db.income_by_source(start, end, include_hidden=False)
        if by_source:
            name, amount = by_source[0]
            share = (amount / income * 100) if income else 0
            self.stat_top.set(name, f"{format_cents(amount, currency)} · {share:.0f}%")
        else:
            self.stat_top.set("--", "nothing logged yet")

        counted = [row for row in rows if not is_hidden(row)]
        total = sum(row["amount_cents"] for row in counted)
        noun = "entry" if len(counted) == 1 else "entries"
        text = f"{len(counted):,} {noun} · {format_cents(total, currency)}"
        left_out = len(rows) - len(counted)
        if left_out:
            text += f" · {left_out:,} not counted"
        self.summary.setText(text if rows else "Nothing matches these filters.")
        self.header.set_subtitle(
            "Everything coming in. Deposits found in an imported CSV land here too."
        )
        self._sync_buttons()

    def _period_label(self) -> str:
        return self.period_filter.currentText().lower()

    def _sync_buttons(self, *_) -> None:
        count = len(self._selected_ids())
        self.edit_button.setEnabled(count == 1)
        self.delete_button.setEnabled(count >= 1)

    # ------------------------------------------------------------ shown rows

    def _set_shown(self, row, shown: bool) -> None:
        """One tick box. Only this page's figures change."""
        self.db.set_hidden("income", [row["id"]], not shown)
        self.refresh()

    def _set_all_shown(self, shown: bool) -> None:
        """Both buttons act on what the filters are showing, not the whole log.

        Hiding everything in a search is how a question like "what if none of
        this counted" gets asked; hiding rows nobody can see would only be
        confusing later.
        """
        rows = self._current_rows()
        if not rows:
            return
        self.db.set_hidden("income", [r["id"] for r in rows], not shown)
        self.refresh()

    def _selected_ids(self) -> list[int]:
        selection = self.table.selectionModel()
        ids = []
        for index in selection.selectedRows() if selection else []:
            row = self.model.row_at(index.row())
            if row is not None:
                ids.append(int(row["id"]))
        return ids

    # ---------------------------------------------------------------- actions

    def add_income(self) -> None:
        dialog = IncomeDialog(self.db.income_sources(), self.db.currency, parent=self)
        if dialog.exec():
            self.db.add_income(**dialog.values())
            self.refresh_sources()
            self.refresh()
            self.on_changed()

    def edit_selected(self) -> None:
        ids = self._selected_ids()
        if len(ids) != 1:
            return
        row = self.db.conn.execute(
            "SELECT * FROM income WHERE id = ?", (ids[0],)
        ).fetchone()
        if row is None:
            return
        dialog = IncomeDialog(
            self.db.income_sources(), self.db.currency, row=row, parent=self
        )
        if dialog.exec():
            self.db.update_income(ids[0], **dialog.values())
            self.refresh_sources()
            self.refresh()
            self.on_changed()

    def delete_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        noun = "entry" if len(ids) == 1 else f"{len(ids)} entries"
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
            self.db.delete_income(ids)
            self.refresh()
            self.on_changed()
