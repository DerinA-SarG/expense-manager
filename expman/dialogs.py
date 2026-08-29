"""Dialogs: expenses, subscriptions, income, goals and category admin."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCalendarWidget,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .money import format_cents, parse_amount
from .recurrence import CYCLES, advance, monthly_cents
from .theme import active_palette
from .widgets import SortItem, align_headers, configure_columns, filling

DATE_FORMAT = "d MMM yyyy"


def _pretty(value: date) -> str:
    """DATE_FORMAT for prose. strftime has no portable unpadded day."""
    return f"{value.day} {value:%b %Y}"


def to_qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


def from_qdate(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def _style_calendar(cal: QCalendarWidget) -> None:
    """Make the popup calendar match the rest of the app.

    QCalendarWidget paints the day-name row and the weekend columns from
    QTextCharFormat, not the stylesheet, so left alone they keep Qt's defaults:
    day names in a colour that vanishes against a dark surface, and Saturday and
    Sunday in red. The week-number column is dropped too -- it is a seventh of
    the popup's width spent on something no one is picking a billing date by.
    """
    pal = active_palette()
    cal.setVerticalHeaderFormat(
        QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
    )
    cal.setHorizontalHeaderFormat(
        QCalendarWidget.HorizontalHeaderFormat.SingleLetterDayNames
    )
    cal.setGridVisible(False)

    header = QTextCharFormat()
    header.setForeground(QColor(pal["muted"]))
    header.setFontWeight(QFont.Weight.DemiBold)
    cal.setHeaderTextFormat(header)

    day = QTextCharFormat()
    day.setForeground(QColor(pal["text"]))
    for weekday in Qt.DayOfWeek:
        cal.setWeekdayTextFormat(weekday, day)


def _date_edit(value: date) -> QDateEdit:
    edit = QDateEdit(to_qdate(value))
    edit.setCalendarPopup(True)
    edit.setDisplayFormat(DATE_FORMAT)
    _style_calendar(edit.calendarWidget())
    return edit


class FormDialog(QDialog):
    """Shared chrome: stacked label/field rows, an error line, and footer buttons."""

    def __init__(self, title: str, parent=None, width: int = 420):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(22, 20, 22, 18)
        self._outer.setSpacing(14)

        heading = QLabel(title)
        heading.setObjectName("H1")
        self._outer.addWidget(heading)

        self.form = QVBoxLayout()
        self.form.setSpacing(12)
        self._outer.addLayout(self.form)

        self.error = QLabel("")
        self.error.setObjectName("ErrorLabel")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        self._outer.addWidget(self.error)

        self._outer.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("Primary")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._on_save)
        footer.addWidget(cancel)
        footer.addWidget(self.save_button)
        self._outer.addLayout(footer)

    def add_row(self, label: str, field: QWidget, hint: str = "") -> QWidget:
        block = QVBoxLayout()
        block.setContentsMargins(0, 0, 0, 0)
        block.setSpacing(5)
        caption = QLabel(label)
        caption.setObjectName("FieldLabel")
        block.addWidget(caption)
        block.addWidget(field)
        if hint:
            note = QLabel(hint)
            note.setObjectName("Muted")
            note.setWordWrap(True)
            block.addWidget(note)
        wrapper = QWidget()
        wrapper.setLayout(block)
        self.form.addWidget(wrapper)
        return wrapper

    def add_columns(self, *fields: QWidget) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        for label, field in fields:
            block = QVBoxLayout()
            block.setContentsMargins(0, 0, 0, 0)
            block.setSpacing(5)
            caption = QLabel(label)
            caption.setObjectName("FieldLabel")
            block.addWidget(caption)
            block.addWidget(field)
            holder = QWidget()
            holder.setLayout(block)
            row.addWidget(holder, 1)
        wrapper = QWidget()
        wrapper.setLayout(row)
        self.form.addWidget(wrapper)

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.setVisible(True)

    def _on_save(self) -> None:
        try:
            self.validate()
        except ValueError as exc:
            self.show_error(str(exc))
            return
        self.accept()

    def validate(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


def _category_box(
    categories: list[str],
    current: str | None,
    placeholder: str = "Pick one or type a new category",
) -> QComboBox:
    box = QComboBox()
    box.setEditable(True)
    box.addItems(categories)
    box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    box.lineEdit().setPlaceholderText(placeholder)
    if current:
        box.setCurrentText(current)
    elif categories:
        box.setCurrentIndex(0)
    return box


class ExpenseDialog(FormDialog):
    def __init__(self, categories, currency="$", row=None, parent=None):
        super().__init__("Edit expense" if row else "Add expense", parent)
        self.currency = currency
        self.row = row
        self.amount_cents = 0

        self.date_field = _date_edit(
            date.fromisoformat(row["spent_on"]) if row else date.today()
        )
        self.amount_field = QLineEdit(
            f"{row['amount_cents'] / 100:.2f}" if row else ""
        )
        self.amount_field.setPlaceholderText("0.00")
        self.add_columns(
            ("Date", self.date_field),
            (f"Amount ({currency})", self.amount_field),
        )

        self.category_field = _category_box(
            categories, row["category"] if row else None
        )
        self.add_row("Category", self.category_field)

        self.description_field = QLineEdit(row["description"] if row else "")
        self.description_field.setPlaceholderText("What was it for?")
        self.add_row("Description", self.description_field)

        self.notes_field = QTextEdit(row["notes"] if row else "")
        self.notes_field.setPlaceholderText("Optional")
        self.notes_field.setFixedHeight(64)
        self.add_row("Notes", self.notes_field)

        if row and row["subscription_id"] is not None:
            self.show_error(
                "This charge was posted by a subscription. Editing it here changes "
                "only this one entry, not the subscription."
            )
            self.error.setObjectName("Muted")

        self.amount_field.setFocus()

    def validate(self) -> None:
        self.amount_cents = parse_amount(self.amount_field.text())
        if not self.category_field.currentText().strip():
            raise ValueError("Pick a category.")

    def values(self) -> dict:
        return {
            "spent_on": from_qdate(self.date_field.date()),
            "amount_cents": self.amount_cents,
            "category": self.category_field.currentText().strip(),
            "description": self.description_field.text().strip(),
            "notes": self.notes_field.toPlainText().strip(),
        }


class SubscriptionDialog(FormDialog):
    def __init__(self, categories, currency="$", row=None, parent=None):
        super().__init__("Edit subscription" if row else "Add subscription", parent, width=460)
        self.currency = currency
        self.row = row
        self.amount_cents = 0

        self.name_field = QLineEdit(row["name"] if row else "")
        self.name_field.setPlaceholderText("Netflix, Spotify, gym membership...")
        self.add_row("Name", self.name_field)

        self.amount_field = QLineEdit(
            f"{row['amount_cents'] / 100:.2f}" if row else ""
        )
        self.amount_field.setPlaceholderText("0.00")

        self.cycle_field = QComboBox()
        for key, (label, _) in CYCLES.items():
            self.cycle_field.addItem(label, key)
        if row:
            index = self.cycle_field.findData(row["cycle"])
            if index >= 0:
                self.cycle_field.setCurrentIndex(index)
        else:
            self.cycle_field.setCurrentIndex(self.cycle_field.findData("monthly"))

        self.add_columns(
            (f"Amount ({currency})", self.amount_field),
            ("Billing cycle", self.cycle_field),
        )

        self.equivalent = QLabel("")
        self.equivalent.setObjectName("Muted")
        self.form.addWidget(self.equivalent)
        self.amount_field.textChanged.connect(self._refresh_equivalent)
        self.cycle_field.currentIndexChanged.connect(self._refresh_equivalent)

        self.category_field = _category_box(
            categories, row["category"] if row else "Subscriptions"
        )
        self.add_row("Category", self.category_field)

        self.start_field = _date_edit(
            date.fromisoformat(row["start_date"]) if row else date.today()
        )
        self.add_row("First billed on", self.start_field)

        # No "next charge" field: the billing date and the cycle already say
        # when every future charge lands, and a second date that disagreed with
        # them was only ever a way to silently skip one.
        self.due_hint = QLabel("")
        self.due_hint.setObjectName("Muted")
        self.due_hint.setWordWrap(True)
        self.form.addWidget(self.due_hint)
        self.start_field.dateChanged.connect(self._refresh_due_hint)
        self.cycle_field.currentIndexChanged.connect(self._refresh_due_hint)

        self.active_field = QCheckBox("Active — post charges to the expense log")
        self.active_field.setChecked(bool(row["active"]) if row else True)
        self.form.addWidget(self.active_field)

        self.notes_field = QTextEdit(row["notes"] if row else "")
        self.notes_field.setPlaceholderText("Optional")
        self.notes_field.setFixedHeight(56)
        self.add_row("Notes", self.notes_field)

        self._refresh_equivalent()
        self._refresh_due_hint()
        self.name_field.setFocus()

    @property
    def cycle(self) -> str:
        return self.cycle_field.currentData()

    def _refresh_equivalent(self) -> None:
        try:
            cents = parse_amount(self.amount_field.text())
        except ValueError:
            self.equivalent.setText("")
            return
        monthly = monthly_cents(cents, self.cycle)
        yearly = monthly * 12
        self.equivalent.setText(
            f"Works out to {format_cents(monthly, self.currency)} per month "
            f"/ {format_cents(yearly, self.currency)} per year."
        )

    def _refresh_due_hint(self) -> None:
        start = from_qdate(self.start_field.date())
        today = date.today()
        if start > today:
            self.due_hint.setText(
                f"First charge posts to your expense log on {_pretty(start)}, "
                "then once every billing cycle after that."
            )
            return
        if self.row is not None:
            # Editing: some of these charges are already in the log, and
            # counting them again here would promise a second helping.
            self.due_hint.setText(
                "Charges post to your expense log automatically, one per "
                "billing cycle from the first billing date."
            )
            return
        pending = self._charges_due_by(start, today)
        if pending == 1:
            self.due_hint.setText(
                "This is already due, so 1 charge is added to your expense log "
                "when you save. Later ones post on their own."
            )
        else:
            self.due_hint.setText(
                f"{pending} charges have come due since then, so they are added "
                "to your expense log when you save. Later ones post on their own."
            )

    def _charges_due_by(self, start: date, today: date) -> int:
        """How many charges this schedule has already run up, start date included."""
        count = 0
        due = start
        while due <= today and count < 520:
            due = advance(due, self.cycle, start.day)
            count += 1
        return count

    def validate(self) -> None:
        if not self.name_field.text().strip():
            raise ValueError("Give the subscription a name.")
        self.amount_cents = parse_amount(self.amount_field.text())
        if not self.category_field.currentText().strip():
            raise ValueError("Pick a category.")

    def values(self) -> dict:
        return {
            "name": self.name_field.text().strip(),
            "amount_cents": self.amount_cents,
            "category": self.category_field.currentText().strip(),
            "cycle": self.cycle,
            "start_date": from_qdate(self.start_field.date()),
            "active": self.active_field.isChecked(),
            "notes": self.notes_field.toPlainText().strip(),
        }


class DeleteEverythingDialog(QDialog):
    """Wipe some or all of the database, behind a deliberate confirmation.

    There is no undo and no server-side copy, so the barriers are proportionate:
    the exact counts are shown, a backup is offered and taken by default, and
    the word has to be typed out. A checkbox alone is too easy to click through
    for something this final.
    """

    PHRASE = "DELETE"

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.removed: dict[str, int] = {}
        self.backup_path = None

        self.setWindowTitle("Delete data")
        self.setModal(True)
        self.setMinimumWidth(480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(12)

        heading = QLabel("Delete data")
        heading.setObjectName("H1")
        outer.addWidget(heading)

        blurb = QLabel(
            "Choose what to clear out. This cannot be undone -- the app keeps no "
            "copy of its own beyond the backup below."
        )
        blurb.setObjectName("Subtle")
        blurb.setWordWrap(True)
        outer.addWidget(blurb)

        counts = db.counts()
        self.switches: dict[str, QCheckBox] = {}
        for key, (label, _) in db.WIPEABLE.items():
            held = counts.get(key, 0)
            box = QCheckBox(f"{label} — {held:,} record{'s' if held != 1 else ''}")
            box.setChecked(True)
            box.setEnabled(held > 0 or key == "categories")
            if key == "subscriptions":
                box.setToolTip(
                    "Also removes the charges these subscriptions posted to your "
                    "expense log. Expenses you entered by hand are kept."
                )
            if key == "categories":
                box.setToolTip("The built-in categories and sources are restored.")
            box.stateChanged.connect(self._sync)
            self.switches[key] = box
            outer.addWidget(box)

        # Set apart from the list above: this one is a safeguard, not another
        # thing to delete, and flush against them it reads as one.
        outer.addSpacing(10)

        self.backup_field = QCheckBox("Save a backup copy first (recommended)")
        self.backup_field.setChecked(True)
        self.backup_field.setToolTip(
            "Writes a timestamped copy of the database next to the original, so "
            "this is recoverable if you change your mind."
        )
        outer.addWidget(self.backup_field)

        self.confirm_field = QLineEdit()
        self.confirm_field.setPlaceholderText(self.PHRASE)
        self.confirm_field.textChanged.connect(self._sync)
        wrapper = QVBoxLayout()
        wrapper.setContentsMargins(0, 0, 0, 0)
        wrapper.setSpacing(5)
        caption = QLabel(f"Type {self.PHRASE} to confirm")
        caption.setObjectName("FieldLabel")
        wrapper.addWidget(caption)
        wrapper.addWidget(self.confirm_field)
        holder = QWidget()
        holder.setLayout(wrapper)
        outer.addWidget(holder)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self._wipe)
        footer.addWidget(cancel)
        footer.addWidget(self.delete_button)
        outer.addLayout(footer)

        self._sync()

    def selected(self) -> list[str]:
        return [k for k, box in self.switches.items() if box.isChecked() and box.isEnabled()]

    def _sync(self, *_) -> None:
        chosen = self.selected()
        typed = self.confirm_field.text().strip() == self.PHRASE
        self.delete_button.setEnabled(bool(chosen) and typed)
        if not chosen:
            self.status.setText("Nothing selected.")
        elif not typed:
            self.status.setText(f"Type {self.PHRASE} above to enable the button.")
        else:
            self.status.setText(f"{len(chosen)} kind(s) of record will be deleted.")

    def _wipe(self) -> None:
        if self.backup_field.isChecked():
            try:
                self.backup_path = self.db.backup_to()
            except OSError as exc:
                self.status.setText(f"Backup failed, nothing deleted: {exc}")
                return
        self.removed = self.db.wipe(self.selected())
        self.accept()


class CategoryManagerDialog(QDialog):
    """Rename, merge and delete categories.

    Categories used to be insert-only: a typo stayed in the dropdown for good and
    the entries filed under it were stranded. Renaming onto a name that already
    exists is deliberately a merge, which is how that gets fixed after the fact.
    """

    COLUMNS = ["Category", "Expenses", "Total", "Subscriptions"]

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.changed = False

        self.setWindowTitle("Categories")
        self.setModal(True)
        self.resize(640, 520)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(12)

        heading = QLabel("Categories")
        heading.setObjectName("H1")
        outer.addWidget(heading)

        blurb = QLabel(
            "Renaming a category onto one that already exists merges the two. "
            "A category still in use cannot be deleted -- merge it instead."
        )
        blurb.setObjectName("Subtle")
        blurb.setWordWrap(True)
        outer.addWidget(blurb)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self.rename_selected)
        self.table.itemSelectionChanged.connect(self._sync_buttons)

        configure_columns(self.table, stretch=0)
        align_headers(self.table, right={1, 2, 3})
        outer.addWidget(self.table, 1)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.rename_button = QPushButton("Rename...")
        self.rename_button.clicked.connect(self.rename_selected)
        self.merge_button = QPushButton("Merge into...")
        self.merge_button.clicked.connect(self.merge_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete_selected)
        for button in (self.rename_button, self.merge_button, self.delete_button):
            footer.addWidget(button)
        footer.addStretch(1)
        done = QPushButton("Done")
        done.setObjectName("Primary")
        done.clicked.connect(self.accept)
        footer.addWidget(done)
        outer.addLayout(footer)

        self.refresh()

    # ------------------------------------------------------------------ table

    def refresh(self) -> None:
        usage = self.db.category_usage()
        currency = self.db.currency

        with filling(self.table, autosize=range(1, len(self.COLUMNS))):
            self.table.setRowCount(len(usage))
            for r, row in enumerate(usage):
                cells = [
                    SortItem(row["name"], row["name"].lower()),
                    SortItem(f"{row['expenses']:,}", row["expenses"]),
                    SortItem(
                        format_cents(row["total_cents"], currency), row["total_cents"]
                    ),
                    SortItem(f"{row['subscriptions']:,}", row["subscriptions"]),
                ]
                for c, item in enumerate(cells):
                    if c:
                        item.setTextAlignment(
                            int(
                                Qt.AlignmentFlag.AlignRight
                                | Qt.AlignmentFlag.AlignVCenter
                            )
                        )
                    self.table.setItem(r, c, item)
        self._sync_buttons()

    def _selected(self) -> dict | None:
        model = self.table.selectionModel()
        rows = model.selectedRows() if model else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return None
        name = item.text()
        return next((u for u in self.db.category_usage() if u["name"] == name), None)

    def _sync_buttons(self) -> None:
        row = self._selected()
        self.rename_button.setEnabled(row is not None)
        self.merge_button.setEnabled(row is not None)

        in_use = bool(row and (row["expenses"] or row["subscriptions"]))
        self.delete_button.setEnabled(row is not None and not in_use)
        if in_use:
            self.delete_button.setToolTip(
                "Still in use. Merge it into another category instead."
            )
            self.status.setText(
                f"'{row['name']}' holds {row['expenses']} expense(s) and "
                f"{row['subscriptions']} subscription(s), so it cannot be deleted."
            )
        else:
            self.delete_button.setToolTip("")
            self.status.setText("")

    # ---------------------------------------------------------------- actions

    def rename_selected(self) -> None:
        row = self._selected()
        if row is None:
            return
        old = row["name"]
        new, ok = QInputDialog.getText(
            self, "Rename category", f"New name for '{old}':", text=old
        )
        if not ok:
            return
        new = new.strip()
        if not new or new == old:
            return

        existing = {c.lower(): c for c in self.db.categories()}
        if new.lower() in existing and existing[new.lower()] != old:
            target = existing[new.lower()]
            if not self._confirm_merge(old, target):
                return
            new = target

        self._apply(lambda: self.db.rename_category(old, new))

    def merge_selected(self) -> None:
        row = self._selected()
        if row is None:
            return
        source = row["name"]
        others = [c for c in self.db.categories() if c != source]
        if not others:
            self.status.setText("There is no other category to merge into.")
            return
        target, ok = QInputDialog.getItem(
            self, "Merge category", f"Move everything in '{source}' into:", others, 0, False
        )
        if ok and target and self._confirm_merge(source, target):
            self._apply(lambda: self.db.rename_category(source, target))

    def delete_selected(self) -> None:
        row = self._selected()
        if row is None:
            return
        name = row["name"]
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Delete category")
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setText(f"Delete '{name}'?")
        confirm.setInformativeText("Nothing is filed under it, so no entries are affected.")
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirm.exec() == QMessageBox.StandardButton.Yes:
            self._apply(lambda: self.db.delete_category(name))

    def _confirm_merge(self, source: str, target: str) -> bool:
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Merge categories")
        confirm.setIcon(QMessageBox.Icon.Question)
        confirm.setText(f"Merge '{source}' into '{target}'?")
        confirm.setInformativeText(
            f"Every expense and subscription filed under '{source}' moves to "
            f"'{target}', and '{source}' is removed. This cannot be undone."
        )
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return confirm.exec() == QMessageBox.StandardButton.Yes

    def _apply(self, action) -> None:
        try:
            action()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.changed = True
        self.refresh()


class IncomeDialog(FormDialog):
    """Money in. The mirror of ExpenseDialog, with a source instead of a category."""

    def __init__(self, sources, currency="$", row=None, parent=None):
        super().__init__("Edit income" if row else "Add income", parent)
        self.currency = currency
        self.amount_cents = 0

        self.date_field = _date_edit(
            date.fromisoformat(row["received_on"]) if row else date.today()
        )
        self.amount_field = QLineEdit(f"{row['amount_cents'] / 100:.2f}" if row else "")
        self.amount_field.setPlaceholderText("0.00")
        self.add_columns(
            ("Date received", self.date_field),
            (f"Amount ({currency})", self.amount_field),
        )

        self.source_field = _category_box(
            sources,
            row["source"] if row else None,
            placeholder="Pick one or type a new source",
        )
        self.add_row("Source", self.source_field)

        self.description_field = QLineEdit(row["description"] if row else "")
        self.description_field.setPlaceholderText("Where did it come from?")
        self.add_row("Description", self.description_field)

        self.notes_field = QTextEdit(row["notes"] if row else "")
        self.notes_field.setPlaceholderText("Optional")
        self.notes_field.setFixedHeight(64)
        self.add_row("Notes", self.notes_field)

        self.amount_field.setFocus()

    def validate(self) -> None:
        self.amount_cents = parse_amount(self.amount_field.text())
        if not self.source_field.currentText().strip():
            raise ValueError("Pick a source.")

    def values(self) -> dict:
        return {
            "received_on": from_qdate(self.date_field.date()),
            "amount_cents": self.amount_cents,
            "source": self.source_field.currentText().strip(),
            "description": self.description_field.text().strip(),
            "notes": self.notes_field.toPlainText().strip(),
        }


class GoalDialog(FormDialog):
    """A savings goal: a target, and the share of income that feeds it."""

    def __init__(self, currency="$", goal=None, typical_income=0, other_pct=0.0, parent=None):
        super().__init__("Edit goal" if goal else "New savings goal", parent, width=460)
        self.currency = currency
        self.amount_cents = 0
        # Used only to make the percentage concrete while you are choosing it.
        self.typical_income = typical_income
        self.other_pct = other_pct

        self.name_field = QLineEdit(goal["name"] if goal else "")
        self.name_field.setPlaceholderText("Emergency fund, new laptop, holiday...")
        self.add_row("Goal", self.name_field)

        self.target_field = QLineEdit(
            f"{goal['target_cents'] / 100:.2f}" if goal else ""
        )
        self.target_field.setPlaceholderText("0.00")
        self.add_row(
            f"Target amount ({currency})",
            self.target_field,
            "How much you are aiming to put aside in total.",
        )

        # A share is set in whole per cent; the box stays a short number and a
        # sign, with the sentence explaining it left to the hint below. Decimals
        # come back only for a goal already cut at a fraction of a per cent --
        # rounding that on an unrelated edit would quietly change the rate.
        share = float(goal["allocation_pct"]) if goal else 0.0
        self.allocation_field = QDoubleSpinBox()
        self.allocation_field.setRange(0.0, 100.0)
        self.allocation_field.setDecimals(0 if share == int(share) else 1)
        self.allocation_field.setSingleStep(1.0)
        self.allocation_field.setSuffix("%")
        self.allocation_field.setValue(share)
        self.allocation_field.setFixedWidth(96)
        self.allocation_field.valueChanged.connect(self._refresh_allocation_hint)
        row = self.add_row("Set aside automatically", self.allocation_field)
        # A field narrower than the form is centred in it unless it is told
        # otherwise, which would leave it floating away from every other label.
        row.layout().setAlignment(
            self.allocation_field, Qt.AlignmentFlag.AlignLeft
        )

        self.allocation_hint = QLabel("")
        self.allocation_hint.setObjectName("Muted")
        self.allocation_hint.setWordWrap(True)
        self.form.addWidget(self.allocation_hint)

        self.notes_field = QTextEdit(goal["notes"] if goal else "")
        self.notes_field.setPlaceholderText("Optional")
        self.notes_field.setFixedHeight(64)
        self.add_row("Notes", self.notes_field)

        self._refresh_allocation_hint()
        self.name_field.setFocus()

    def _refresh_allocation_hint(self, *_) -> None:
        pct = self.allocation_field.value()
        if pct <= 0:
            self.allocation_hint.setText(
                "Nothing is set aside automatically -- you add to this goal by hand."
            )
            return

        # The box carries a bare number now, so the hint has to say what the
        # percentage is taken out of.
        parts = [f"{pct:g}% of every income entry goes to this goal."]
        if self.typical_income:
            share = round(self.typical_income * pct / 100)
            parts.append(
                f"On a typical {format_cents(self.typical_income, self.currency)} "
                f"that is {format_cents(share, self.currency)}."
            )
        combined = self.other_pct + pct
        if combined > 100:
            parts.append(
                f"Careful: your goals would claim {combined:g}% of every income "
                "entry between them, which is more than comes in."
            )
        elif self.other_pct:
            parts.append(f"Your goals would claim {combined:g}% of income in total.")
        self.allocation_hint.setText(" ".join(parts))

    def validate(self) -> None:
        if not self.name_field.text().strip():
            raise ValueError("Give the goal a name.")
        self.amount_cents = parse_amount(self.target_field.text())

    def values(self) -> dict:
        return {
            "name": self.name_field.text().strip(),
            "target_cents": self.amount_cents,
            "allocation_pct": self.allocation_field.value(),
            "notes": self.notes_field.toPlainText().strip(),
        }


class ContributionDialog(FormDialog):
    """Money moved into a goal, or taken back out of it."""

    def __init__(self, goal_name: str, currency="$", parent=None):
        super().__init__(f"Add to {goal_name}", parent)
        self.currency = currency
        self.amount_cents = 0

        self.date_field = _date_edit(date.today())
        self.amount_field = QLineEdit()
        self.amount_field.setPlaceholderText("0.00")
        self.add_columns(
            ("Date", self.date_field),
            (f"Amount ({currency})", self.amount_field),
        )

        self.withdraw_field = QCheckBox("Taking money back out instead")
        self.withdraw_field.setToolTip(
            "Records the amount as a withdrawal, reducing what the goal holds."
        )
        self.form.addWidget(self.withdraw_field)

        self.note_field = QLineEdit()
        self.note_field.setPlaceholderText("Optional")
        self.add_row("Note", self.note_field)

        self.amount_field.setFocus()

    def validate(self) -> None:
        self.amount_cents = parse_amount(self.amount_field.text())

    def values(self) -> dict:
        # A withdrawal is stored as a negative contribution, so the goal's total
        # stays a single SUM with no special-casing on read.
        sign = -1 if self.withdraw_field.isChecked() else 1
        return {
            "made_on": from_qdate(self.date_field.date()),
            "amount_cents": sign * self.amount_cents,
            "note": self.note_field.text().strip(),
        }
