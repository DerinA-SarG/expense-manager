"""A table model for the two ledgers that grow without limit.

QTableWidget allocates one item object per cell every time it is refilled, so a
3,000-row log costs 15,000 allocations per refresh and gets slower with every
import. A model hands out cell values on demand instead: only the rows actually
on screen are ever asked for, so a refresh costs the same whether the log holds
fifty rows or fifty thousand.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from datetime import date as _date


def pretty_date(iso: str) -> str:
    """ISO date to "3 Aug 2026". Only ever called for rows on screen."""
    value = _date.fromisoformat(iso)
    return f"{value.day} {value.strftime('%b %Y')}"


RIGHT = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
LEFT = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


@dataclass
class Column:
    """One column: how to show a row, sort it, colour it and describe it."""

    title: str
    display: Callable[[Any, str], str]
    key: Callable[[Any], Any] | None = None
    align: int = LEFT
    # (row, palette) -> colour name, or None to leave the default ink.
    ink: Callable[[Any, dict], str | None] | None = None
    tooltip: Callable[[Any], str] | None = None
    stretch: bool = False

    def sort_value(self, row) -> Any:
        return self.key(row) if self.key else self.display(row, "")


class LedgerModel(QAbstractTableModel):
    """Rows stay in their native sqlite3.Row form; columns do the formatting.

    Deliberately not a dataclass: the generated __init__ would touch attributes
    before QAbstractTableModel's own constructor had built the C++ side.
    """

    def __init__(self, columns: list[Column], palette: dict, currency: str = "$", parent=None):
        super().__init__(parent)
        self.columns = columns
        self.palette = palette
        self.currency = currency
        self.rows: list = []
        self._sort_column = 0
        self._sort_order = Qt.SortOrder.DescendingOrder

    # ------------------------------------------------------------------- data

    def set_rows(self, rows, currency: str | None = None) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        if currency is not None:
            self.currency = currency
        self._apply_sort()
        self.endResetModel()

    def set_palette(self, palette: dict) -> None:
        self.palette = palette
        if self.rows:
            top, bottom = self.index(0, 0), self.index(len(self.rows) - 1, len(self.columns) - 1)
            self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.ForegroundRole])

    def row_at(self, proxy_row: int):
        if 0 <= proxy_row < len(self.rows):
            return self.rows[proxy_row]
        return None

    # -------------------------------------------------------- model interface

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        column = self.columns[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            return column.display(row, self.currency)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return column.align
        if role == Qt.ItemDataRole.ForegroundRole and column.ink:
            name = column.ink(row, self.palette)
            return QColor(name) if name else None
        if role == Qt.ItemDataRole.ToolTipRole and column.tooltip:
            return column.tooltip(row) or None
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section].title
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self.columns[section].align
        return None

    # ---------------------------------------------------------------- sorting

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder) -> None:
        self._sort_column = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        self._apply_sort()
        self.layoutChanged.emit()

    def _apply_sort(self) -> None:
        if not self.rows or not (0 <= self._sort_column < len(self.columns)):
            return
        column = self.columns[self._sort_column]
        self.rows.sort(
            key=column.sort_value,
            reverse=self._sort_order == Qt.SortOrder.DescendingOrder,
        )


# Auto-sizing a column normally measures every row. Sampling is enough to pick a
# sensible width and keeps the cost flat as the log grows.
RESIZE_SAMPLE = 48
ROW_HEIGHT = 38


def ledger_view(model: LedgerModel, stretch: int, parent=None):
    """A QTableView wired to a LedgerModel, tuned for long logs."""
    from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

    view = QTableView(parent)
    view.setModel(model)
    view.setShowGrid(False)
    view.setWordWrap(False)
    view.setAlternatingRowColors(False)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setSortingEnabled(True)
    view.sortByColumn(0, Qt.SortOrder.DescendingOrder)

    # Fixed row heights let the view skip measuring rows it never paints.
    rows = view.verticalHeader()
    rows.setVisible(False)
    rows.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    rows.setDefaultSectionSize(ROW_HEIGHT)

    head = view.horizontalHeader()
    head.setResizeContentsPrecision(RESIZE_SAMPLE)
    for col in range(model.columnCount()):
        head.setSectionResizeMode(
            col,
            QHeaderView.ResizeMode.Stretch
            if col == stretch
            else QHeaderView.ResizeMode.ResizeToContents,
        )
    head.setHighlightSections(False)
    return view
