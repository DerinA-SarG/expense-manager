"""Main window: sidebar navigation over a stack of pages."""
from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, QThread, QUrl, Qt, QTimer, Signal
from PySide6.QtGui import (
    QActionGroup,
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import updates
from .db import Database
from .dialogs import DeleteEverythingDialog
from .pages.expenses import ExpensesPage
from .pages.goals import GoalsPage
from .pages.income import IncomePage
from .pages.overview import OverviewPage
from .pages.subscriptions import SubscriptionsPage
from .theme import gear_icon, palette, prepare_assets, stylesheet

APP_NAME = "Expense Manager"

CURRENCIES = ["$", "€", "£", "¥", "₹", "kr", "R$", "CHF", "A$", "C$"]

NAV = [
    ("Overview", "Where the money goes"),
    ("Expenses", "Every logged charge"),
    ("Income", "Everything coming in"),
    ("Subscriptions", "Recurring charges"),
    ("Goals", "Savings targets"),
]


class _UpdateCheck(QThread):
    """Runs the git comparison off the GUI thread.

    A fetch waits on a network, and a window that stops repainting for the
    duration reads as a hang -- which is the one thing this app has already
    been taught not to look like.
    """

    answered = Signal(object)

    def run(self) -> None:
        try:
            self.answered.emit(updates.check())
        except Exception as exc:  # shown to the user; never swallowed
            self.answered.emit(exc)


def _s(count: int) -> str:
    return "" if count == 1 else "s"


def make_icon(color: str, background: str) -> QIcon:
    """A small donut, so the taskbar entry is not a generic interpreter icon."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setBrush(QColor(background))
    painter.drawEllipse(22, 22, 20, 20)
    painter.end()
    return QIcon(pixmap)


class MainWindow(QWidget):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.pal = palette(db.get_setting("theme", "dark"))
        self._update_check: _UpdateCheck | None = None

        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.setMinimumSize(920, 600)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.overview = OverviewPage(
            db,
            self.pal,
            on_add_expense=lambda: self.expenses.add_expense(),
            on_add_subscription=lambda: self.subscriptions.add_subscription(),
        )
        self.expenses = ExpensesPage(db, self.pal, on_changed=self._data_changed)
        self.subscriptions = SubscriptionsPage(db, self.pal, on_changed=self._data_changed)
        self.income = IncomePage(db, self.pal, on_changed=self._data_changed)
        self.goals = GoalsPage(db, self.pal, on_changed=self._data_changed)

        # Order must match NAV.
        self.pages = (
            self.overview,
            self.expenses,
            self.income,
            self.subscriptions,
            self.goals,
        )
        for page in self.pages:
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)

        self.apply_theme()
        self.overview.empty.set_palette(self.pal)
        for page in (self.income, self.goals):
            page.empty.set_palette(self.pal)
        self.nav_buttons.button(0).setChecked(True)
        self.stack.setCurrentIndex(0)

        # Post anything that came due while the app was closed, once the window
        # is actually on screen so the notice is not orphaned.
        QTimer.singleShot(120, self._post_due_on_launch)

    # ---------------------------------------------------------------- sidebar

    def _build_sidebar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(228)

        column = QVBoxLayout(bar)
        column.setContentsMargins(16, 22, 16, 16)
        column.setSpacing(6)

        brand = QLabel(APP_NAME)
        brand.setObjectName("Brand")
        tagline = QLabel("Local · single user")
        tagline.setObjectName("BrandSub")
        column.addWidget(brand)
        column.addWidget(tagline)
        column.addSpacing(20)

        self.nav_buttons = QButtonGroup(self)
        self.nav_buttons.setExclusive(True)
        for index, (label, tip) in enumerate(NAV):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(38)
            self.nav_buttons.addButton(button, index)
            column.addWidget(button)
        self.nav_buttons.idClicked.connect(self._navigate)

        column.addStretch(1)

        # Everything that is not navigation lives behind one gear, so the
        # sidebar reads as a list of places rather than a settings panel.
        self.settings_button = QPushButton("  Settings")
        self.settings_button.setObjectName("Settings")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setMinimumHeight(38)
        self.settings_button.setToolTip("Currency, appearance, backups and data")
        self.settings_button.clicked.connect(self._show_settings)
        column.addWidget(self.settings_button)

        return bar

    # ---------------------------------------------------------------- settings

    def _show_settings(self) -> None:
        menu = self._settings_menu()
        # The button sits at the bottom of the window, so drop the menu upwards
        # rather than off the edge of the screen.
        corner = self.settings_button.mapToGlobal(QPoint(0, 0))
        menu.exec(QPoint(corner.x(), corner.y() - menu.sizeHint().height()))

    def _settings_menu(self) -> QMenu:
        """Built fresh each time, so the ticks always reflect the real state."""
        menu = QMenu(self)

        currency = menu.addMenu("Currency")
        group = QActionGroup(currency)
        group.setExclusive(True)
        for symbol in CURRENCIES:
            action = currency.addAction(symbol)
            action.setCheckable(True)
            action.setChecked(symbol == self.db.currency)
            action.triggered.connect(lambda _=False, s=symbol: self._set_currency(s))
            group.addAction(action)
        currency.addSeparator()
        custom = currency.addAction("Something else...")
        custom.triggered.connect(self._pick_currency)

        dark = menu.addAction("Dark mode")
        dark.setCheckable(True)
        dark.setChecked(self.pal["name"] == "dark")
        dark.triggered.connect(self._toggle_theme)

        menu.addSeparator()

        backup = menu.addAction("Back up now...")
        backup.setToolTip("Save a timestamped copy of your database")
        backup.triggered.connect(self._backup_now)

        reveal = menu.addAction("Show data folder")
        reveal.setToolTip(str(self.db.path))
        reveal.triggered.connect(self._open_data_folder)

        check = menu.addAction("Check for updates...")
        check.setToolTip("Ask the project this copy came from whether it has moved on")
        check.setEnabled(self._update_check is None)
        check.triggered.connect(self.check_for_updates)

        menu.addSeparator()

        delete = menu.addAction("Delete data...")
        delete.triggered.connect(self.delete_everything)
        return menu

    def _pick_currency(self) -> None:
        symbol, ok = QInputDialog.getText(
            self, "Currency", "Symbol to show before amounts:", text=self.db.currency
        )
        if ok and symbol.strip():
            self._set_currency(symbol)

    def _backup_now(self) -> None:
        try:
            path = self.db.backup_to()
        except OSError as exc:
            QMessageBox.warning(self, "Backup failed", str(exc))
            return
        QMessageBox.information(
            self, "Backup saved", f"A copy of your database was saved to:\n{path}"
        )

    def _open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.db.path.parent)))

    # ----------------------------------------------------------------- updates

    def check_for_updates(self) -> None:
        """Compare this copy against the checkout it came from.

        The only network call the app ever makes, and it only happens from
        here. Nothing on disk changes until the update is accepted.
        """
        if self._update_check is not None:
            return
        self._update_check = _UpdateCheck(self)
        self._update_check.answered.connect(self._update_answer)
        self._update_check.finished.connect(self._forget_update_check)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._update_check.start()

    def _forget_update_check(self) -> None:
        """Dropped only once the thread has actually finished running."""
        if self._update_check is not None:
            self._update_check.deleteLater()
            self._update_check = None

    def _update_answer(self, result) -> None:
        QApplication.restoreOverrideCursor()
        if isinstance(result, Exception):
            QMessageBox.information(self, "Check for updates", str(result))
            return

        if not result.available:
            note = "This copy is up to date."
            if result.ahead:
                note += (
                    f"\n\n{result.ahead} commit{_s(result.ahead)} here "
                    "have not been pushed."
                )
            QMessageBox.information(self, "Check for updates", note)
            return

        ask = QMessageBox(self)
        ask.setWindowTitle("Update available")
        ask.setIcon(QMessageBox.Icon.Question)
        ask.setText(
            f"{result.behind} update{_s(result.behind)} waiting on {result.branch}."
        )
        told = "Bring this copy up to date?"
        if result.dirty:
            told += (
                "\n\nThere are uncommitted changes here. The update will refuse "
                "rather than write over them."
            )
        if updates.is_frozen():
            told += (
                "\n\nThis window is the packaged build, which carries its own "
                "frozen copy of the code. Updating changes the source, not the "
                ".exe -- it has to be rebuilt before the change reaches here."
            )
        ask.setInformativeText(told)
        ask.setDetailedText("\n".join(f"- {s}" for s in result.subjects))
        ask.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        ask.setDefaultButton(QMessageBox.StandardButton.Yes)
        if ask.exec() != QMessageBox.StandardButton.Yes:
            return

        try:
            updates.pull()
        except updates.GitUnavailable as exc:
            QMessageBox.warning(self, "Update failed", str(exc))
            return

        if updates.is_frozen():
            done = (
                "The source is up to date, but this window is still running the "
                "old frozen copy. Rebuild it with:\n\n"
                "    python tools/build_exe.py\n\n"
                "then start it again."
            )
        else:
            done = "Updated. Restart Expense Manager to run the new version."
        QMessageBox.information(self, "Update", done)

    # ----------------------------------------------------------------- events

    def _navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        # Every page reloads from the database as it is opened, so whatever
        # happened while it was hidden is picked up here.
        self.stack.currentWidget().refresh()

    def _data_changed(self) -> None:
        """Something changed the data; refresh the page being looked at.

        A change anywhere invalidates all six pages, but rebuilding the five
        nobody is looking at is wasted work -- and it grows with the size of the
        log. Navigation refreshes on open, so the hidden ones catch up for free.
        """
        self.stack.currentWidget().refresh()

    def _set_currency(self, symbol: str) -> None:
        symbol = symbol.strip()
        if not symbol:
            return
        self.db.set_setting("currency_symbol", symbol)
        # Pages read the symbol from the database as they render, so the hidden
        # ones pick it up when they are next opened.
        self.stack.currentWidget().refresh()

    def _toggle_theme(self, *_) -> None:
        new_theme = "light" if self.pal["name"] == "dark" else "dark"
        self.db.set_setting("theme", new_theme)
        self.pal = palette(new_theme)
        self.apply_theme()
        for page in self.pages:
            page.set_palette(self.pal)

    def apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            assets = prepare_assets(self.pal, self.db.path.parent / "assets")
            app.setStyleSheet(stylesheet(self.pal, assets))
            app.setWindowIcon(make_icon(self.pal["accent"], self.pal["surface"]))
        self.settings_button.setIcon(gear_icon(self.pal["text_secondary"]))

    def delete_everything(self) -> None:
        dialog = DeleteEverythingDialog(self.db, parent=self)
        if not dialog.exec() or not dialog.removed:
            return

        # Filters and dropdowns still hold categories that may no longer exist.
        self.expenses.refresh_categories()
        self.income.refresh_sources()
        for page in self.pages:
            page.refresh()

        lines = [f"{count:,} {name}" for name, count in dialog.removed.items()]
        detail = "Deleted " + ", ".join(lines) + "."
        if dialog.backup_path:
            detail += "\n\nA backup was saved to:\n" + str(dialog.backup_path)
        QMessageBox.information(self, "Data deleted", detail)

    def _post_due_on_launch(self) -> None:
        posted = self.db.post_due_subscriptions()
        if not posted:
            return
        for page in self.pages:
            page.refresh()
        QMessageBox.information(
            self,
            "Subscriptions caught up",
            f"{posted} subscription charge{'s' if posted != 1 else ''} came due while "
            f"the app was closed and {'have' if posted != 1 else 'has'} been added to "
            "your expense log.",
        )

    def closeEvent(self, event):
        self.db.close()
        super().closeEvent(event)


def run(db_path: str | None = None) -> int:
    if sys.platform == "win32":
        # Without this Windows groups the window under the Python interpreter.
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "zephr.expensemanager.1"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)
    # Fusion renders identically on Windows and Linux and draws the control
    # primitives (combo carets, sort indicators) that the stylesheet leaves alone.
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ExpenseManager")

    db = Database(db_path)
    window = MainWindow(db)
    window.show()
    return app.exec()
