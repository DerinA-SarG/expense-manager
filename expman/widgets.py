"""Small shared UI pieces."""
from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHeaderView,
    QTableWidgetItem,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap


class Card(QFrame):
    """Rounded surface panel."""

    def __init__(self, parent=None, padding: int = 18, spacing: int = 12):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)


class StatCard(Card):
    """Label / big number / footnote."""

    def __init__(self, label: str, value: str = "--", note: str = "", parent=None):
        super().__init__(parent, padding=16, spacing=4)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.label = QLabel(label)
        self.label.setObjectName("StatLabel")

        self.value = QLabel(value)
        self.value.setObjectName("StatValue")

        self.note = QLabel(note)
        self.note.setObjectName("StatNote")
        self.note.setVisible(bool(note))

        self.body.addWidget(self.label)
        self.body.addWidget(self.value)
        self.body.addWidget(self.note)

    def set(self, value: str, note: str = "") -> None:
        self.value.setText(value)
        self.note.setText(note)
        self.note.setVisible(bool(note))


class PageHeader(QWidget):
    """Title, subtitle, and a slot on the right for actions."""

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("H1")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("Subtle")
        self.subtitle.setVisible(bool(subtitle))
        text.addWidget(self.title)
        text.addWidget(self.subtitle)

        row.addLayout(text)
        row.addStretch(1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        row.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))


class Pill(QLabel):
    """Small status chip. Always carries a word, never colour alone."""

    def __init__(self, text: str, color: str, subtle_bg: str, parent=None):
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_colors(color, subtle_bg)

    def set_colors(self, color: str, subtle_bg: str) -> None:
        self.setStyleSheet(
            f"color: {color}; background: {subtle_bg}; border-radius: 9px;"
            f"padding: 2px 9px; font-size: 11px; font-weight: 600;"
        )


def soft_shadow(widget: QWidget, blur: int = 24, alpha: int = 40) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setXOffset(0)
    effect.setYOffset(2)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)


def hline(color: str) -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {color};")
    return line


def configure_columns(table, stretch: int) -> None:
    """Set up a table that gets refilled, without the ResizeToContents trap.

    ResizeToContents looks like the obvious mode for a data column, but as a
    *persistent* mode on a visible table it makes Qt re-measure every row of
    that column on every single setItem -- filling 200 rows becomes seconds of
    frozen UI, and it degrades quadratically. Columns are Interactive here and
    sized once per fill by `filling()` instead.
    """
    head = table.horizontalHeader()
    for col in range(table.columnCount()):
        head.setSectionResizeMode(
            col,
            QHeaderView.ResizeMode.Stretch
            if col == stretch
            else QHeaderView.ResizeMode.Interactive,
        )
    head.setHighlightSections(False)


@contextmanager
def filling(table, autosize=()):
    """Repopulate a table cheaply: no repaints, no sorting, no signals.

    Signals are blocked because setRowCount and setItem each churn the
    selection, and the selection handlers read back into the model while it is
    still being mutated. Callers re-sync their buttons after the fill.
    """
    table.setUpdatesEnabled(False)
    sorting = table.isSortingEnabled()
    table.setSortingEnabled(False)
    blocked = table.blockSignals(True)
    try:
        yield
    finally:
        table.blockSignals(blocked)
        table.setSortingEnabled(sorting)
        for col in autosize:
            table.resizeColumnToContents(col)
        table.setUpdatesEnabled(True)


def align_headers(table, right: set[int] | None = None) -> None:
    """Match each header label to the alignment of the column beneath it.

    Qt centres header text by default, which leaves the label floating away from
    the values it names -- badly so for right-aligned money columns.
    """
    right = right or set()
    for col in range(table.columnCount()):
        item = table.horizontalHeaderItem(col)
        if item is None:
            continue
        side = (
            Qt.AlignmentFlag.AlignRight if col in right else Qt.AlignmentFlag.AlignLeft
        )
        item.setTextAlignment(int(side | Qt.AlignmentFlag.AlignVCenter))


class EmptyState(QWidget):
    """Centred placeholder shown instead of a chart or table with nothing in it.

    A blank chart frame tells a first-time user nothing; this says what is
    missing and offers the action that fixes it.
    """

    BODY_WIDTH = 400

    def __init__(self, title: str, body: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Transparent")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        self.art = QLabel()
        self.art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.art)

        self.title = QLabel(title)
        self.title.setObjectName("EmptyTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)

        self.body = QLabel(body)
        self.body.setObjectName("Subtle")
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setWordWrap(True)
        # A wrapped QLabel only reports an honest height once its width is
        # pinned; with a mere maximum it under-reports and overlaps its
        # neighbours.
        self.body.setFixedWidth(self.BODY_WIDTH)
        self.body.setMinimumHeight(
            self.body.fontMetrics().boundingRect(
                0, 0, self.BODY_WIDTH, 0, int(Qt.TextFlag.TextWordWrap), body
            ).height()
        )
        layout.addWidget(self.body, alignment=Qt.AlignmentFlag.AlignCenter)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.actions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        holder = QWidget()
        holder.setObjectName("Transparent")
        holder.setLayout(self.actions)
        layout.addWidget(holder)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def set_palette(self, pal: dict) -> None:
        """Redraw the decorative ring in the current theme's ink."""
        size = 76
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.setDevicePixelRatio(2.0)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(pal["grid"]))
        pen.setWidthF(11.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(12, 12, size - 24, size - 24)

        # One live-coloured arc, so the ring reads as a chart waiting for data.
        pen.setColor(QColor(pal["accent"]))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(12, 12, size - 24, size - 24, 90 * 16, -70 * 16)
        painter.end()

        self.art.setPixmap(pixmap)


class SortItem(QTableWidgetItem):
    """Table cell that sorts on a supplied key rather than its display text.

    Without this, an amount column sorts as a string and $9.00 lands above
    $80.00, and a formatted date sorts alphabetically.
    """

    def __init__(self, text: str, key):
        super().__init__(text)
        self.key = key
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def __lt__(self, other):
        if isinstance(other, SortItem):
            return self.key < other.key
        return super().__lt__(other)


def debounce(widget, slot, delay_ms: int = 250):
    """Run `slot` once the user stops typing, not on every keystroke.

    Each character in a search box otherwise costs a SQL query and a full table
    reload; on a long log that is what makes typing feel sticky.
    """
    from PySide6.QtCore import QTimer

    timer = QTimer(widget)
    timer.setSingleShot(True)
    timer.setInterval(delay_ms)
    timer.timeout.connect(slot)
    # Kept on the widget so it lives exactly as long as the widget does.
    widget._debounce_timer = timer
    return timer.start
