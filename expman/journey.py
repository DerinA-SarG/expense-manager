"""The three steps of a sitting, drawn down the side of the window.

Keeping this app up to date is the same short routine every time: log what came
in, log what went out, then set aside what the goals are owed. The panel is a
prompt for that routine, not a record of it -- it starts empty at every launch
and remembers nothing between them, because "what have I done since I opened
this" is the only question it is answering. A tick that survived a restart would
be claiming something about last Tuesday.

Nothing here writes to the database or reads from it; the window tells the panel
what has happened.
"""
from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

# key, label, and the index in app.NAV the step sends you to.
STEPS = [
    ("income", "Enter Income", 2),
    ("expenses", "Enter Expenses", 1),
    ("goals", "Update Goals", 4),
]

# How many times the node for the next step breathes after something
# changes. It is a nudge, not a siren: a pulse that never stopped would have
# this widget repainting for as long as the window is open.
PULSE_BURSTS = 3

ROW_HEIGHT = 40
RADIUS = 8.0
RAIL_X = 13.0
LABEL_X = 34
TOP_PAD = 6


class StepTrack(QWidget):
    """The rail itself: a node per step, and a line filling in behind them."""

    stepClicked = Signal(int)

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.pal = palette
        self.done: set[str] = set()
        # 0..1 along the whole rail. Eased towards the real figure rather than
        # snapped to it, so a step completing reads as movement rather than as
        # the panel having been redrawn behind your back.
        self.fill = 0.0
        self._target_fill = 0.0
        self._pulse = 0.0
        self._bursts_left = PULSE_BURSTS
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(TOP_PAD * 2 + ROW_HEIGHT * len(STEPS))

        # One timer drives both the fill and the pulse. It runs only while
        # something is actually moving -- a finance app has no business spinning
        # a repaint timer in the background all day.
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ state

    def set_palette(self, palette: dict) -> None:
        self.pal = palette
        self.update()

    def set_done(self, done) -> None:
        self.done = set(done)
        complete = [key for key, _, _ in STEPS if key in self.done]
        # The rail runs between the first and last node, so a step is worth one
        # gap, not one row: with three nodes, one done fills half of it.
        gaps = max(len(STEPS) - 1, 1)
        self._target_fill = min(len(complete) / gaps, 1.0)
        # Something changed, so the next step is worth pointing at again.
        self._pulse = 0.0
        self._bursts_left = PULSE_BURSTS
        self._timer.start()
        self.update()

    @property
    def current(self) -> int:
        """The first step still waiting, or -1 once they are all done."""
        for index, (key, _, _) in enumerate(STEPS):
            if key not in self.done:
                return index
        return -1

    def _tick(self) -> None:
        moving = abs(self._target_fill - self.fill) > 0.002
        if moving:
            self.fill += (self._target_fill - self.fill) * 0.18
        else:
            self.fill = self._target_fill

        pulsing = self.current != -1 and self._bursts_left > 0
        if pulsing:
            self._pulse += 0.045
            if self._pulse >= 1.0:
                self._pulse = 0.0
                self._bursts_left -= 1
        else:
            self._pulse = 0.0
            if not moving:
                # Nothing left to animate: stop rather than repaint for ever.
                self._timer.stop()
        self.update()

    # ---------------------------------------------------------------- drawing

    def _node_y(self, index: int) -> float:
        return TOP_PAD + ROW_HEIGHT * index + ROW_HEIGHT / 2

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        top, bottom = self._node_y(0), self._node_y(len(STEPS) - 1)
        rail = QPen(QColor(self.pal["grid"]))
        rail.setWidthF(2.0)
        rail.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(rail)
        painter.drawLine(QLineF(RAIL_X, top, RAIL_X, bottom))

        if self.fill > 0:
            lit = QPen(QColor(self.pal["good"]))
            lit.setWidthF(2.0)
            lit.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(lit)
            painter.drawLine(
                QLineF(RAIL_X, top, RAIL_X, top + (bottom - top) * self.fill)
            )

        current = self.current
        for index, (key, label, _) in enumerate(STEPS):
            centre = self._node_y(index)
            done = key in self.done
            live = index == current

            if live and self._pulse > 0:
                # A halo breathing out from the node someone is being asked to
                # do next. Alpha only, so it never competes with the nav buttons.
                glow = QColor(self.pal["accent"])
                glow.setAlpha(int(70 * (1.0 - self._pulse)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                grown = RADIUS + 5.0 * self._pulse
                painter.drawEllipse(
                    QRectF(RAIL_X - grown, centre - grown, grown * 2, grown * 2)
                )

            box = QRectF(RAIL_X - RADIUS, centre - RADIUS, RADIUS * 2, RADIUS * 2)
            if done:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self.pal["good"]))
                painter.drawEllipse(box)

                tick = QPen(QColor(self.pal["accent_text"]))
                tick.setWidthF(2.0)
                tick.setCapStyle(Qt.PenCapStyle.RoundCap)
                tick.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(tick)
                painter.drawPolyline(
                    [
                        QPointF(RAIL_X - 3.6, centre + 0.2),
                        QPointF(RAIL_X - 1.0, centre + 2.8),
                        QPointF(RAIL_X + 3.8, centre - 3.0),
                    ]
                )
            else:
                ring = QPen(QColor(self.pal["accent"] if live else self.pal["axis"]))
                ring.setWidthF(2.0 if live else 1.5)
                painter.setPen(ring)
                painter.setBrush(QColor(self.pal["surface"]))
                painter.drawEllipse(box)

            font = QFont(self.font())
            font.setPixelSize(12)
            font.setWeight(QFont.Weight.DemiBold if live else QFont.Weight.Normal)
            painter.setFont(font)
            if done:
                ink = self.pal["text_secondary"]
            elif live:
                ink = self.pal["text"]
            else:
                ink = self.pal["muted"]
            painter.setPen(QPen(QColor(ink)))
            painter.drawText(
                QRectF(LABEL_X, centre - ROW_HEIGHT / 2, self.width() - LABEL_X, ROW_HEIGHT),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                label,
            )
        painter.end()

    # ----------------------------------------------------------------- events

    def _step_at(self, y: float) -> int:
        index = int((y - TOP_PAD) // ROW_HEIGHT)
        return index if 0 <= index < len(STEPS) else -1

    def mousePressEvent(self, event):
        index = self._step_at(event.position().y())
        if index != -1:
            self.stepClicked.emit(STEPS[index][2])
        super().mousePressEvent(event)


class JourneyPanel(QFrame):
    """The titled block the track sits in, at the foot of the sidebar."""

    navigate = Signal(int)

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("Journey")
        self.done: set[str] = set()

        column = QVBoxLayout(self)
        column.setContentsMargins(4, 10, 4, 6)
        column.setSpacing(4)

        self.heading = QLabel("This session")
        self.heading.setObjectName("StatLabel")
        column.addWidget(self.heading)

        self.track = StepTrack(palette)
        self.track.stepClicked.connect(self.navigate)
        column.addWidget(self.track)

        self.footnote = QLabel("")
        self.footnote.setObjectName("BrandSub")
        self.footnote.setWordWrap(True)
        column.addWidget(self.footnote)

        self._sync()

    def set_palette(self, palette: dict) -> None:
        self.track.set_palette(palette)

    def complete(self, key: str) -> None:
        """Tick a step off. Doing something twice is not an error."""
        if key not in {step for step, _, _ in STEPS}:
            return
        self.done.add(key)
        self._sync()

    def reset(self) -> None:
        self.done.clear()
        self._sync()

    def _sync(self) -> None:
        self.track.set_done(self.done)
        left = len(STEPS) - len(self.done)
        self.footnote.setText(
            "All three done." if not left else f"{left} left · resets on restart"
        )
