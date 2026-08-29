"""Colour palettes and the application stylesheet.

The two modes are selected, not flipped: the dark series steps are chosen for the
dark surface rather than derived from the light ones. Series hues are assigned in
a fixed order and never cycled -- past the eighth category the overview folds the
tail into a neutral "Other" slice.
"""
from __future__ import annotations

LIGHT = {
    "name": "light",
    "page": "#f9f9f7",
    "surface": "#fcfcfb",
    "surface_alt": "#f1f0ec",
    "surface_hover": "#ecebe6",
    "text": "#0b0b0b",
    "text_secondary": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "border": "#dedcd5",
    "accent": "#2a78d6",
    "accent_hover": "#256abf",
    "accent_text": "#ffffff",
    "good": "#006300",
    "critical": "#d03b3b",
    "warning": "#fab219",
    "other": "#898781",
    "series": [
        "#2a78d6",  # blue
        "#eb6834",  # orange
        "#1baf7a",  # aqua
        "#eda100",  # yellow
        "#e87ba4",  # magenta
        "#008300",  # green
        "#4a3aa7",  # violet
        "#e34948",  # red
    ],
}

DARK = {
    "name": "dark",
    "page": "#0d0d0d",
    "surface": "#1a1a19",
    "surface_alt": "#232322",
    "surface_hover": "#2c2c2a",
    "text": "#ffffff",
    "text_secondary": "#c3c2b7",
    "muted": "#898781",
    "grid": "#2c2c2a",
    "axis": "#383835",
    "border": "#2c2c2a",
    "accent": "#3987e5",
    "accent_hover": "#5598e7",
    "accent_text": "#ffffff",
    "good": "#0ca30c",
    "critical": "#e66767",
    "warning": "#fab219",
    "other": "#898781",
    "series": [
        "#3987e5",  # blue
        "#d95926",  # orange
        "#199e70",  # aqua
        "#c98500",  # yellow
        "#d55181",  # magenta
        "#008300",  # green
        "#9085e9",  # violet
        "#e66767",  # red
    ],
}

PALETTES = {"light": LIGHT, "dark": DARK}


def palette(name: str) -> dict:
    return PALETTES.get(name, DARK)


def prepare_assets(pal: dict, cache_dir) -> dict[str, str]:
    """Render the caret icons the stylesheet needs and return their paths.

    Once a QComboBox is styled at all, Qt stops falling back to the widget
    style's arrow primitive -- it draws nothing unless the stylesheet hands it an
    actual image. Drawing them here keeps the caret in the palette's own ink
    instead of shipping fixed-colour PNGs that only suit one theme.
    """
    from pathlib import Path

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    scale = 2.0  # render at 2x so the glyph stays crisp on a HiDPI display

    def stroke(name: str, size: int, points, color: str, width: float) -> str:
        pixmap = QPixmap(int(size * scale), int(size * scale))
        # The ratio shrinks the painter's coordinate space to `size` logical
        # units -- the points below are in those units, not device pixels.
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(color))
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline([QPointF(x, y) for x, y in points])
        painter.end()

        target = cache / f"{name}_{pal['name']}.png"
        pixmap.save(str(target))
        # QSS wants forward slashes even on Windows.
        return str(target).replace("\\", "/")

    chevron = [(2.0, 4.0), (5.0, 7.0), (8.0, 4.0)]
    chevron_up = [(2.0, 6.5), (5.0, 3.5), (8.0, 6.5)]
    tick = [(3.5, 8.4), (6.6, 11.5), (12.5, 4.8)]

    return {
        "caret": stroke("caret", 10, chevron, pal["muted"], 1.5),
        "caret_active": stroke("caret_active", 10, chevron, pal["text_secondary"], 1.5),
        "caret_up": stroke("caret_up", 10, chevron_up, pal["muted"], 1.5),
        # Same story as the caret: a styled indicator draws no glyph of its own.
        "check": stroke("check", 16, tick, pal["accent_text"], 2.1),
        "check_menu": stroke("check_menu", 16, tick, pal["text"], 2.1),
    }


def gear_icon(color: str, size: int = 18, teeth: int = 8):
    """A cog drawn to match the palette, rather than a bundled image file.

    Everything else in the chrome is painted from the palette, so a fixed-colour
    PNG would be the one thing that failed to follow the theme.
    """
    import math

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap

    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)

    centre = size / 2
    outer, inner, hole = size * 0.47, size * 0.32, size * 0.13
    step = math.tau / teeth

    path = QPainterPath()
    for i in range(teeth):
        angle = i * step
        # Out to a tooth, along its tip, back down, then around the root.
        for radius, offset in (
            (inner, -step * 0.28),
            (outer, -step * 0.14),
            (outer, step * 0.14),
            (inner, step * 0.28),
        ):
            point = QPointF(
                centre + radius * math.cos(angle + offset),
                centre + radius * math.sin(angle + offset),
            )
            path.lineTo(point) if path.elementCount() else path.moveTo(point)
    path.closeSubpath()

    # Odd-even fill turns the inner circle into a hole rather than a blob.
    path.addEllipse(QPointF(centre, centre), hole, hole)
    path.setFillRule(Qt.FillRule.OddEvenFill)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


def series_color(pal: dict, index: int) -> str:
    """Fixed-order hue for a series slot; anything past the ramp is neutral."""
    colors = pal["series"]
    return colors[index] if 0 <= index < len(colors) else pal["other"]


# QSS uses braces, so this template interpolates with %(name)s rather than str.format.
_QSS = """
QWidget {
    background: %(page)s;
    color: %(text)s;
    font-family: "Segoe UI", system-ui, -apple-system, "Ubuntu", "Cantarell", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog { background: %(page)s; }

QLabel { background: transparent; }
QLabel#H1 { font-size: 22px; font-weight: 600; color: %(text)s; }
QLabel#Subtle { color: %(text_secondary)s; }
QLabel#Muted { color: %(muted)s; font-size: 12px; }
QLabel#StatLabel {
    color: %(muted)s; font-size: 11px; font-weight: 600;
    letter-spacing: 0.6px; text-transform: uppercase;
}
QLabel#StatValue { color: %(text)s; font-size: 24px; font-weight: 600; }
QLabel#StatNote { color: %(text_secondary)s; font-size: 12px; }
QLabel#FieldLabel { color: %(text_secondary)s; font-size: 12px; font-weight: 600; }
QLabel#ErrorLabel { color: %(critical)s; font-size: 12px; }
QLabel#EmptyTitle { color: %(text)s; font-size: 15px; font-weight: 600; }

/* ------------------------------------------------------------------ sidebar */
QFrame#Sidebar { background: %(surface)s; border-right: 1px solid %(border)s; }
QLabel#Brand { font-size: 15px; font-weight: 700; color: %(text)s; }
QLabel#BrandSub { font-size: 11px; color: %(muted)s; }

QPushButton#NavButton {
    background: transparent; border: none; border-radius: 8px;
    padding: 10px 12px; text-align: left;
    color: %(text_secondary)s; font-size: 13px; font-weight: 500;
}
QPushButton#NavButton:hover { background: %(surface_hover)s; color: %(text)s; }
QPushButton#NavButton:checked {
    background: %(accent)s; color: %(accent_text)s; font-weight: 600;
}

/* -------------------------------------------------------------------- cards */
QFrame#Card {
    background: %(surface)s; border: 1px solid %(border)s; border-radius: 12px;
}
QFrame#Divider { background: %(border)s; border: none; max-height: 1px; }

/* ------------------------------------------------------------------ buttons */
QPushButton {
    background: %(surface)s; color: %(text)s;
    border: 1px solid %(border)s; border-radius: 8px;
    padding: 7px 14px; font-size: 13px; font-weight: 500;
}
QPushButton:hover { background: %(surface_hover)s; }
QPushButton:pressed { background: %(surface_alt)s; }
QPushButton:disabled { color: %(muted)s; background: %(surface_alt)s; }

QPushButton#Primary {
    background: %(accent)s; color: %(accent_text)s; border: 1px solid %(accent)s;
    font-weight: 600;
}
QPushButton#Primary:hover { background: %(accent_hover)s; border-color: %(accent_hover)s; }
/* Same trap as #Danger below: the ID selector outranks the plain :disabled rule,
   so without this a disabled primary button still looks clickable. */
QPushButton#Primary:disabled {
    background: %(surface_alt)s; color: %(muted)s; border-color: %(border)s;
}
QPushButton#Danger { color: %(critical)s; }
QPushButton#Danger:hover { background: %(surface_hover)s; }
/* The ID selector outranks the plain :disabled rule, so a disabled destructive
   button would otherwise keep its live red text. */
QPushButton#Danger:disabled { color: %(muted)s; background: %(surface_alt)s; }
QPushButton#Ghost { background: transparent; border-color: transparent; color: %(text_secondary)s; }
QPushButton#Ghost:hover { background: %(surface_hover)s; color: %(text)s; }

/* ------------------------------------------------------------------- inputs */
QLineEdit, QTextEdit, QComboBox, QDateEdit, QDoubleSpinBox, QSpinBox {
    background: %(surface)s; color: %(text)s;
    border: 1px solid %(border)s; border-radius: 8px;
    padding: 7px 10px; selection-background-color: %(accent)s;
    selection-color: %(accent_text)s;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus,
QDateEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {
    border: 1px solid %(accent)s;
}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled {
    color: %(muted)s; background: %(surface_alt)s;
}
QLineEdit#Search { padding-left: 10px; }

QComboBox::drop-down, QDateEdit::drop-down {
    border: none; width: 22px; subcontrol-position: center right; right: 4px;
}
QComboBox::down-arrow, QDateEdit::down-arrow {
    image: url(%(caret)s); width: 10px; height: 10px;
}
QComboBox::down-arrow:hover, QDateEdit::down-arrow:hover { image: url(%(caret_active)s); }
QComboBox QAbstractItemView {
    background: %(surface)s; color: %(text)s;
    border: 1px solid %(border)s; border-radius: 8px;
    selection-background-color: %(accent)s; selection-color: %(accent_text)s;
    outline: none; padding: 4px;
}
QDateEdit::up-button, QDateEdit::down-button { width: 0; border: none; }

/* ------------------------------------------------------------------ calendar */
/* The calendar popup is a QTableView inside a QCalendarWidget, so the table
   rules further down land on it uninvited: 9px of cell padding swells every day
   cell until the last weeks are pushed off the popup. Reset the cell box here
   and let the widget size its own grid. */
QCalendarWidget QAbstractItemView::item { padding: 0; border: none; }
/* ::item:selected further down is more specific than any selection-background-
   colour set on the view, so the chosen day needs saying at the same level. */
QCalendarWidget QAbstractItemView::item:selected {
    background: %(accent)s; color: %(accent_text)s;
}
QCalendarWidget QWidget { background: %(surface)s; }
QCalendarWidget QAbstractItemView {
    background: %(surface)s; color: %(text)s;
    alternate-background-color: %(surface)s;
    selection-background-color: %(accent)s; selection-color: %(accent_text)s;
    border: none; outline: none;
}
QCalendarWidget QWidget#qt_calendar_navigationbar {
    background: %(surface_alt)s;
    border-bottom: 1px solid %(grid)s;
    min-height: 36px;
}
QCalendarWidget QToolButton {
    background: transparent; border: none; border-radius: 6px;
    color: %(text)s; font-size: 13px; font-weight: 600; padding: 5px 10px;
}
QCalendarWidget QToolButton:hover { background: %(surface_hover)s; }
/* The month button drops a menu; its default arrow doubles up with the label. */
QCalendarWidget QToolButton::menu-indicator { image: none; width: 0; }
QCalendarWidget QSpinBox {
    background: %(surface)s; color: %(text)s;
    border: 1px solid %(accent)s; border-radius: 6px; padding: 2px 6px;
}

/* Spin boxes keep their steppers -- a percentage is worth nudging -- so they
   need a real hit area and their own arrows, or Qt squeezes them to a sliver. */
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background: transparent; border: none; width: 18px; height: 11px;
    subcontrol-origin: border; right: 4px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url(%(caret_up)s); width: 9px; height: 9px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url(%(caret)s); width: 9px; height: 9px;
}
QSpinBox::up-arrow:hover, QSpinBox::down-arrow:hover,
QDoubleSpinBox::up-arrow:hover, QDoubleSpinBox::down-arrow:hover {
    image: url(%(caret_active)s);
}

QCheckBox { spacing: 8px; color: %(text)s; background: transparent; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid %(axis)s; background: %(surface)s;
}
QCheckBox::indicator:checked {
    background: %(accent)s; border-color: %(accent)s; image: url(%(check)s);
}

/* ------------------------------------------------------------------- tables */
QTableWidget, QTableView {
    background: %(surface)s; alternate-background-color: %(surface_alt)s;
    border: none; gridline-color: transparent;
    selection-background-color: %(surface_hover)s; selection-color: %(text)s;
    outline: none;
}
/* No `color` here: cells set their own foreground (muted sources, green status,
   overdue amber) and a stylesheet colour would silently win over all of it. */
QTableWidget::item, QTableView::item {
    padding: 9px 10px; border-bottom: 1px solid %(grid)s;
}
QTableWidget::item:selected, QTableView::item:selected {
    background: %(surface_hover)s;
}
QHeaderView { background: transparent; }
QHeaderView::section {
    background: %(surface)s; color: %(muted)s;
    padding: 9px 10px; border: none; border-bottom: 1px solid %(axis)s;
    font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
}
QHeaderView::section:hover { color: %(text_secondary)s; }
/* Without an explicit position the sort indicator floats above the label. */
QHeaderView::up-arrow, QHeaderView::down-arrow {
    subcontrol-origin: content; subcontrol-position: center right;
    width: 9px; height: 9px; right: 2px;
}
QTableCornerButton::section { background: %(surface)s; border: none; }

/* --------------------------------------------------------------- scrollbars */
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 2px;
}
QScrollBar::handle:vertical {
    background: %(axis)s; border-radius: 5px; min-height: 28px;
}
QScrollBar::handle:vertical:hover { background: %(muted)s; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal {
    background: %(axis)s; border-radius: 5px; min-width: 28px;
}
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* Plain container widgets inherit the page background from the QWidget rule,
   which paints an opaque rectangle inside a card. Opt them out by name. */
QWidget#Transparent, QWidget#Transparent > QWidget { background: transparent; }

QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

/* --------------------------------------------------------------------- menus */
QMenu {
    background: %(surface)s; color: %(text)s;
    border: 1px solid %(border)s; border-radius: 10px; padding: 6px;
}
QMenu::item {
    padding: 7px 26px 7px 30px; border-radius: 6px; color: %(text)s;
}
QMenu::item:selected { background: %(surface_hover)s; }
QMenu::item:disabled { color: %(muted)s; }
QMenu::separator { height: 1px; background: %(grid)s; margin: 6px 10px; }
QMenu::indicator {
    width: 14px; height: 14px; left: 9px; background: transparent; border: none;
}
QMenu::indicator:checked { image: url(%(check_menu)s); }
QMenu::right-arrow {
    image: url(%(caret)s); width: 9px; height: 9px; right: 10px;
}

QPushButton#Settings {
    background: transparent; border: none; border-radius: 8px;
    padding: 9px 12px; text-align: left;
    color: %(text_secondary)s; font-size: 13px; font-weight: 500;
}
QPushButton#Settings:hover { background: %(surface_hover)s; color: %(text)s; }
QPushButton#Settings::menu-indicator { image: none; width: 0; }

QToolTip {
    background: %(surface)s; color: %(text)s;
    border: 1px solid %(axis)s; border-radius: 6px; padding: 6px 8px;
}

QMessageBox { background: %(surface)s; }
QMessageBox QLabel { color: %(text)s; }
"""


_active: dict = DARK


def active_palette() -> dict:
    """The palette the running app was last styled with.

    A few widgets cannot be reached by the stylesheet -- QCalendarWidget paints
    its day names and weekend columns from QTextCharFormat -- so they need the
    colours directly. Recorded by ``stylesheet`` because that is the one call
    every theme change goes through.
    """
    return _active


def stylesheet(pal: dict, assets: dict[str, str] | None = None) -> str:
    values = dict(pal)
    values.update(assets or {})
    global _active
    _active = pal
    return _QSS % values
