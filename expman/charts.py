"""Custom-painted chart widgets.

The donut and the legend are two views of one dataset and stay hover-synced, so
identity is never carried by colour alone: every slice is also named, valued and
bar-scaled in the list beside it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .money import format_cents, format_compact

# A 2px gap of the surface colour separates adjacent fills.
_GAP_PX = 2.0
_HOVER_GROW_PX = 6.0


@dataclass
class Slice:
    label: str
    cents: int
    color: str

    @property
    def qcolor(self) -> QColor:
        return QColor(self.color)


class DonutChart(QWidget):
    """Ring chart with a hero total in the middle."""

    hoverChanged = Signal(int)  # -1 when nothing is hovered

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.pal = palette
        self.slices: list[Slice] = []
        self.total = 0
        self.currency = "$"
        self.caption = "Total"
        self.subcaption = ""
        self._hover = -1
        self._geometry: list[tuple[float, float]] = []  # (start_deg, sweep_deg) per slice
        self.setMouseTracking(True)
        self.setMinimumSize(260, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # ------------------------------------------------------------------ state

    def set_palette(self, palette: dict) -> None:
        self.pal = palette
        self.update()

    def set_data(
        self,
        slices: list[Slice],
        currency: str = "$",
        caption: str = "Total",
        subcaption: str = "",
    ) -> None:
        self.slices = list(slices)
        self.total = sum(s.cents for s in self.slices)
        self.currency = currency
        self.caption = caption
        # Slices may be fewer than real categories once the tail is folded, so
        # the caller supplies the true count rather than us guessing from len().
        self.subcaption = subcaption or f"{len(self.slices)} categories"
        self._hover = -1
        self.update()

    def set_hover(self, index: int) -> None:
        if index != self._hover:
            self._hover = index
            self.update()

    # ----------------------------------------------------------------- events

    def leaveEvent(self, event):
        if self._hover != -1:
            self._hover = -1
            self.hoverChanged.emit(-1)
            self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        index = self._hit_test(event.position())
        if index != self._hover:
            self._hover = index
            self.hoverChanged.emit(index)
            self.update()
            if index >= 0:
                s = self.slices[index]
                pct = (s.cents / self.total * 100) if self.total else 0
                self.setToolTip(
                    f"{s.label}\n{format_cents(s.cents, self.currency)}  ({pct:.1f}%)"
                )
            else:
                self.setToolTip("")
        super().mouseMoveEvent(event)

    def _hit_test(self, pos: QPointF) -> int:
        if not self._geometry:
            return -1
        cx, cy, outer, inner = self._ring_metrics()
        dx = pos.x() - cx
        dy = cy - pos.y()  # screen y grows downward; flip for maths
        radius = math.hypot(dx, dy)
        if radius < inner or radius > outer + _HOVER_GROW_PX:
            return -1
        theta = math.degrees(math.atan2(dy, dx)) % 360.0
        for i, (start, sweep) in enumerate(self._geometry):
            if (start - theta) % 360.0 <= sweep:
                return i
        return -1

    # ---------------------------------------------------------------- drawing

    def _ring_metrics(self) -> tuple[float, float, float, float]:
        side = min(self.width(), self.height()) - 2 * _HOVER_GROW_PX - 8
        side = max(side, 40.0)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        outer = side / 2.0
        inner = outer * 0.62
        return cx, cy, outer, inner

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        cx, cy, outer, inner = self._ring_metrics()
        if not self.slices or self.total <= 0:
            self._paint_empty(painter, cx, cy, outer, inner)
            painter.end()
            return

        mid_radius = (outer + inner) / 2.0
        gap_deg = math.degrees(_GAP_PX / max(mid_radius, 1.0))

        self._geometry = []
        cursor = 90.0  # start at twelve o'clock
        for s in self.slices:
            sweep = s.cents / self.total * 360.0
            self._geometry.append((cursor, sweep))
            cursor -= sweep

        for i, (s, (start, sweep)) in enumerate(zip(self.slices, self._geometry)):
            hovered = i == self._hover
            grow = _HOVER_GROW_PX if hovered else 0.0
            # Only inset a gap when the slice is wide enough to survive it.
            trim = gap_deg if sweep > gap_deg * 2.5 else 0.0
            a0 = start - trim / 2.0
            span = -(sweep - trim)

            outer_rect = QRectF(
                cx - outer - grow, cy - outer - grow,
                (outer + grow) * 2, (outer + grow) * 2,
            )
            inner_rect = QRectF(cx - inner, cy - inner, inner * 2, inner * 2)

            path = QPainterPath()
            path.arcMoveTo(outer_rect, a0)
            path.arcTo(outer_rect, a0, span)
            path.arcTo(inner_rect, a0 + span, -span)
            path.closeSubpath()

            color = s.qcolor
            if self._hover >= 0 and not hovered:
                color.setAlpha(150)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawPath(path)

        self._paint_centre(painter, cx, cy, inner)
        painter.end()

    HEADLINE_MIN_PT = 10.5

    def _fit_headline(self, cents: int, inner: float) -> tuple[str, QFont]:
        """The exact amount at the largest size that fits inside the hole.

        Abbreviating is a last resort: a rounded figure in the middle of the ring
        that disagrees with the exact total printed above it reads as a bug, so
        shrinking the text is the better trade.
        """
        available = inner * 1.7  # usable chord across the hole, with a margin
        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)

        exact = format_cents(cents, self.currency)
        size = max(13.0, inner * 0.24)
        while size > self.HEADLINE_MIN_PT:
            font.setPointSizeF(size)
            if QFontMetricsF(font).horizontalAdvance(exact) <= available:
                return exact, font
            size -= 0.5

        font.setPointSizeF(self.HEADLINE_MIN_PT)
        if QFontMetricsF(font).horizontalAdvance(exact) <= available:
            return exact, font
        return format_compact(cents, self.currency), font

    def _paint_centre(self, painter: QPainter, cx: float, cy: float, inner: float) -> None:
        if self._hover >= 0:
            s = self.slices[self._hover]
            amount = s.cents
            caption = s.label
            sub = f"{s.cents / self.total * 100:.1f}% of total" if self.total else ""
        else:
            amount = self.total
            caption = self.caption
            sub = self.subcaption

        box = QRectF(cx - inner, cy - inner * 0.75, inner * 2, inner * 1.5)

        headline, font = self._fit_headline(amount, inner)
        painter.setFont(font)
        painter.setPen(QPen(QColor(self.pal["text"])))
        painter.drawText(
            QRectF(box.left(), cy - inner * 0.42, box.width(), inner * 0.6),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            headline,
        )

        font.setPointSizeF(max(8.5, inner * 0.105))
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(QPen(QColor(self.pal["text_secondary"])))
        painter.drawText(
            QRectF(box.left(), cy + inner * 0.14, box.width(), inner * 0.34),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
            self._elide(caption, box.width() - 8, painter),
        )

        if sub:
            font.setPointSizeF(max(7.5, inner * 0.085))
            font.setWeight(QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(QPen(QColor(self.pal["muted"])))
            painter.drawText(
                QRectF(box.left(), cy + inner * 0.42, box.width(), inner * 0.3),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                sub,
            )

    def _paint_empty(self, painter, cx, cy, outer, inner) -> None:
        pen = QPen(QColor(self.pal["grid"]))
        pen.setWidthF(max(6.0, (outer - inner)))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        mid = (outer + inner) / 2.0
        painter.drawEllipse(QPointF(cx, cy), mid, mid)

        font = QFont(self.font())
        font.setPointSizeF(10.0)
        painter.setFont(font)
        painter.setPen(QPen(QColor(self.pal["muted"])))
        painter.drawText(
            QRectF(cx - inner, cy - 20, inner * 2, 40),
            int(Qt.AlignmentFlag.AlignCenter),
            "Nothing logged\nin this period",
        )

    @staticmethod
    def _elide(text: str, width: float, painter: QPainter) -> str:
        metrics = painter.fontMetrics()
        return metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(width))


class CategoryLegend(QWidget):
    """Ranked category list: swatch, name, share bar, amount.

    This is the accurate magnitude read that a ring alone cannot give -- slices
    of similar size are hard to rank by eye, but the bars are directly
    comparable, and every row is directly labelled.
    """

    hoverChanged = Signal(int)

    ROW_H = 44

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.pal = palette
        self.slices: list[Slice] = []
        self.total = 0
        self.currency = "$"
        self._hover = -1
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def set_palette(self, palette: dict) -> None:
        self.pal = palette
        self.update()

    def set_data(self, slices: list[Slice], currency: str = "$") -> None:
        self.slices = list(slices)
        self.total = sum(s.cents for s in self.slices)
        self.currency = currency
        self._hover = -1
        self.setMinimumHeight(max(1, len(self.slices)) * self.ROW_H)
        self.updateGeometry()
        self.update()

    def set_hover(self, index: int) -> None:
        if index != self._hover:
            self._hover = index
            self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(320, max(1, len(self.slices)) * self.ROW_H)

    def leaveEvent(self, event):
        if self._hover != -1:
            self._hover = -1
            self.hoverChanged.emit(-1)
            self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        index = int(event.position().y()) // self.ROW_H
        index = index if 0 <= index < len(self.slices) else -1
        if index != self._hover:
            self._hover = index
            self.hoverChanged.emit(index)
            self.update()
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        if not self.slices:
            painter.setPen(QPen(QColor(self.pal["muted"])))
            painter.drawText(
                self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No categories yet"
            )
            painter.end()
            return

        width = self.width()
        biggest = max(s.cents for s in self.slices) or 1

        base_font = QFont(self.font())
        base_font.setPointSizeF(9.5)
        value_font = QFont(base_font)
        value_font.setWeight(QFont.Weight.DemiBold)

        for i, s in enumerate(self.slices):
            top = i * self.ROW_H
            hovered = i == self._hover

            if hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self.pal["surface_hover"]))
                painter.drawRoundedRect(QRectF(0, top + 2, width, self.ROW_H - 4), 8, 8)

            # swatch
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(s.qcolor)
            painter.drawRoundedRect(QRectF(10, top + 13, 10, 10), 3, 3)

            pct = (s.cents / self.total * 100) if self.total else 0.0

            painter.setFont(base_font)
            painter.setPen(QPen(QColor(self.pal["text"])))
            name_w = width - 150
            painter.drawText(
                QRectF(30, top + 8, name_w, 18),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                painter.fontMetrics().elidedText(
                    s.label, Qt.TextElideMode.ElideRight, int(name_w)
                ),
            )

            painter.setFont(value_font)
            painter.drawText(
                QRectF(width - 130, top + 8, 120, 18),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                format_cents(s.cents, self.currency),
            )

            # share bar -- length is relative to the largest category
            bar_y = top + 29
            bar_w = width - 40 - 46
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.pal["grid"]))
            painter.drawRoundedRect(QRectF(30, bar_y, bar_w, 4), 2, 2)

            fill = max(3.0, bar_w * (s.cents / biggest))
            color = s.qcolor
            if self._hover >= 0 and not hovered:
                color.setAlpha(150)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(30, bar_y, fill, 4), 2, 2)

            painter.setFont(base_font)
            painter.setPen(QPen(QColor(self.pal["muted"])))
            painter.drawText(
                QRectF(width - 130, bar_y - 7, 120, 18),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{pct:.1f}%",
            )

        painter.end()


class ProgressRing(QWidget):
    """A donut showing how much of a savings target has been reached.

    Unlike the category donut this has exactly two arcs -- saved and remaining --
    so the percentage in the middle is the whole story.
    """

    THICKNESS = 0.24  # ring width as a fraction of the radius

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.pal = palette
        self.saved = 0
        self.target = 0
        self.currency = "$"
        self.setMinimumSize(150, 150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_palette(self, palette: dict) -> None:
        self.pal = palette
        self.update()

    def set_data(self, saved: int, target: int, currency: str = "$") -> None:
        self.saved = saved
        self.target = target
        self.currency = currency
        self.update()

    @property
    def ratio(self) -> float:
        return (self.saved / self.target) if self.target > 0 else 0.0

    def _arc_color(self) -> str:
        if self.saved < 0:
            return self.pal["critical"]
        if self.ratio >= 1.0:
            return self.pal["good"]
        return self.pal["accent"]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        side = min(self.width(), self.height()) - 8
        radius = max(side / 2.0, 20.0)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        width = max(6.0, radius * self.THICKNESS)
        box = QRectF(cx - radius + width / 2, cy - radius + width / 2,
                     (radius - width / 2) * 2, (radius - width / 2) * 2)

        track = QPen(QColor(self.pal["grid"]))
        track.setWidthF(width)
        track.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(track)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(box)

        fraction = max(0.0, min(self.ratio, 1.0))
        if fraction > 0:
            arc = QPen(QColor(self._arc_color()))
            arc.setWidthF(width)
            arc.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arc)
            # Qt angles are 1/16th degrees, counter-clockwise from 3 o'clock;
            # start at twelve and sweep clockwise.
            painter.drawArc(box, 90 * 16, int(-fraction * 360 * 16))

        font = QFont(self.font())
        font.setPointSizeF(max(11.0, radius * 0.26))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QPen(QColor(self.pal["text"])))
        painter.drawText(
            QRectF(cx - radius, cy - radius * 0.45, radius * 2, radius * 0.6),
            int(Qt.AlignmentFlag.AlignCenter),
            f"{self.ratio * 100:.0f}%",
        )

        font.setPointSizeF(max(7.5, radius * 0.13))
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QPen(QColor(self.pal["text_secondary"])))
        painter.drawText(
            QRectF(cx - radius, cy + radius * 0.12, radius * 2, radius * 0.4),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
            format_compact(self.saved, self.currency),
        )
        painter.end()
