"""CSV import: pick a file, confirm the column mapping, review, import.

Nothing is written until the preview has been shown, because a mis-detected
column would otherwise silently fill the log with garbage that is tedious to
unpick.
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import csvio
from .money import format_cents
from .widgets import align_headers, configure_columns, filling

NONE_LABEL = "(none)"
PREVIEW_LIMIT = 500

STATUS_TEXT = {
    "duplicate": "Already logged",
    "skipped": "Skipped",
    "error": "Unreadable",
}


def status_text(row) -> str:
    if row.status == "new":
        return "Income" if row.is_income else "Will import"
    return STATUS_TEXT.get(row.status, row.status)


class ImportDialog(QDialog):
    def __init__(self, db, palette: dict, parent=None):
        super().__init__(parent)
        self.db = db
        self.pal = palette
        self.imported = 0
        self.imported_expenses = 0
        self.imported_income = 0

        self.headers: list[str] = []
        self.records: list[dict] = []
        self.profile: csvio.Profile | None = None
        self.rows: list[csvio.ParsedRow] = []
        self._loading = False

        self.setWindowTitle("Import from CSV")
        self.setModal(True)
        self.resize(940, 700)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(12)

        heading = QLabel("Import from CSV")
        heading.setObjectName("H1")
        outer.addWidget(heading)

        blurb = QLabel(
            "Download a transaction export from your bank or card issuer and open it "
            "here. Discover and Capital One layouts are recognised automatically; "
            "anything else you can map by hand below. Money out becomes an expense, "
            "money in becomes income."
        )
        blurb.setObjectName("Subtle")
        blurb.setWordWrap(True)
        outer.addWidget(blurb)

        outer.addWidget(self._build_file_row())
        self.mapping_box = self._build_mapping()
        outer.addWidget(self.mapping_box)
        outer.addWidget(self._build_options())

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Description", "Amount", "Category / source", "Status"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        configure_columns(self.table, stretch=1)
        align_headers(self.table, right={2})
        outer.addWidget(self.table, 1)

        self.summary = QLabel("Choose a file to begin.")
        self.summary.setObjectName("Subtle")
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.import_button = QPushButton("Import")
        self.import_button.setObjectName("Primary")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._do_import)
        footer.addWidget(cancel)
        footer.addWidget(self.import_button)
        outer.addLayout(footer)

        self._set_mapping_visible(False)

    # ------------------------------------------------------------------ build

    def _build_file_row(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("Transparent")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.path_field = QLineEdit()
        self.path_field.setReadOnly(True)
        self.path_field.setPlaceholderText("No file chosen")
        row.addWidget(self.path_field, 1)

        browse = QPushButton("Choose file...")
        browse.clicked.connect(self.choose_file)
        row.addWidget(browse)
        return holder

    def _build_mapping(self) -> QFrame:
        box = QFrame()
        box.setObjectName("Card")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self.format_label = QLabel("")
        self.format_label.setObjectName("StatLabel")
        layout.addWidget(self.format_label)

        grid = QHBoxLayout()
        grid.setSpacing(10)
        self.field_boxes: dict[str, QComboBox] = {}
        for key, label in (
            ("date", "Date"),
            ("description", "Description"),
            ("amount", "Amount"),
            ("debit", "Debit"),
            ("credit", "Credit"),
            ("category", "Category"),
        ):
            column = QVBoxLayout()
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(4)
            caption = QLabel(label)
            caption.setObjectName("FieldLabel")
            combo = QComboBox()
            combo.currentIndexChanged.connect(self._on_mapping_changed)
            self.field_boxes[key] = combo
            column.addWidget(caption)
            column.addWidget(combo)
            holder = QWidget()
            holder.setObjectName("Transparent")
            holder.setLayout(column)
            grid.addWidget(holder, 1)
        layout.addLayout(grid)

        # Second line: how the direction of each row is decided. Either a column
        # says so outright, or the sign of the amount does.
        direction = QHBoxLayout()
        direction.setSpacing(10)

        kind_column = QVBoxLayout()
        kind_column.setContentsMargins(0, 0, 0, 0)
        kind_column.setSpacing(4)
        kind_caption = QLabel("Debit/credit column")
        kind_caption.setObjectName("FieldLabel")
        self.kind_box = QComboBox()
        self.kind_box.setToolTip(
            "A column that says which way the money went, used when the amount "
            "itself is unsigned."
        )
        self.kind_box.currentIndexChanged.connect(self._on_mapping_changed)
        self.field_boxes["kind"] = self.kind_box
        kind_column.addWidget(kind_caption)
        kind_column.addWidget(self.kind_box)
        kind_holder = QWidget()
        kind_holder.setObjectName("Transparent")
        kind_holder.setLayout(kind_column)
        direction.addWidget(kind_holder, 1)

        sign_column = QVBoxLayout()
        sign_column.setContentsMargins(0, 0, 0, 0)
        sign_column.setSpacing(4)
        self.sign_caption = QLabel("Otherwise, by sign")
        self.sign_caption.setObjectName("FieldLabel")
        self.sign_box = QComboBox()
        self.sign_box.addItem("Positive amounts are money spent", 1)
        self.sign_box.addItem("Negative amounts are money spent", -1)
        self.sign_box.currentIndexChanged.connect(self._on_mapping_changed)
        sign_column.addWidget(self.sign_caption)
        sign_column.addWidget(self.sign_box)
        self.sign_holder = QWidget()
        self.sign_holder.setObjectName("Transparent")
        self.sign_holder.setLayout(sign_column)
        direction.addWidget(self.sign_holder, 2)

        layout.addLayout(direction)
        return box

    def _build_options(self) -> QWidget:
        holder = QWidget()
        holder.setObjectName("Transparent")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self.use_issuer = QCheckBox("Use the categories from the file")
        self.use_issuer.setChecked(True)
        self.use_issuer.setToolTip(
            "Issuer categories such as 'Supermarkets' are translated to yours "
            "where there is an obvious match; the rest come through as-is."
        )
        self.use_issuer.stateChanged.connect(self._on_mapping_changed)
        row.addWidget(self.use_issuer)

        row.addWidget(QLabel("Otherwise file under:"))
        self.fallback = QComboBox()
        self.fallback.addItems(self.db.categories())
        index = self.fallback.findText("Other")
        self.fallback.setCurrentIndex(max(index, 0))
        self.fallback.currentIndexChanged.connect(self._on_mapping_changed)
        row.addWidget(self.fallback)

        self.capture_income = QCheckBox("Bring deposits in as income")
        self.capture_income.setChecked(True)
        self.capture_income.setToolTip(
            "Credits on the statement -- pay, refunds, transfers in -- are added to "
            "the Income page. Untick to leave them out entirely."
        )
        self.capture_income.stateChanged.connect(self._on_mapping_changed)
        row.addWidget(self.capture_income)

        row.addStretch(1)
        return holder

    def _set_mapping_visible(self, visible: bool) -> None:
        self.mapping_box.setVisible(visible)

    # ----------------------------------------------------------------- events

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a CSV export", "", "CSV files (*.csv);;All files (*)"
        )
        if path:
            self.load_path(path)

    def load_path(self, path: str) -> None:
        """Open a file by path. Split out from the picker so it can be driven
        directly by tests and by a caller that already knows the file."""
        self.path_field.setText(path)
        try:
            self.headers, self.records = csvio.read_table(path)
        except OSError as exc:
            self.summary.setText(f"Could not read that file: {exc}")
            return

        if not self.headers or not self.records:
            self.summary.setText("That file has no rows in it.")
            self._set_mapping_visible(False)
            self.table.setRowCount(0)
            self.import_button.setEnabled(False)
            return

        self.profile = csvio.detect(self.headers)
        self._populate_mapping()
        self._set_mapping_visible(True)
        self.reparse()

    def _populate_mapping(self) -> None:
        """Fill the column pickers from the detected profile."""
        self._loading = True
        actual = {csvio.normalise(h): h for h in self.headers}
        for key, combo in self.field_boxes.items():
            combo.clear()
            combo.addItem(NONE_LABEL, None)
            for header in self.headers:
                combo.addItem(header, header)
            guess = getattr(self.profile, key, None)
            chosen = actual.get(csvio.normalise(guess)) if guess else None
            combo.setCurrentIndex(combo.findData(chosen) if chosen else 0)

        self.sign_box.setCurrentIndex(0 if self.profile.expense_sign >= 0 else 1)
        self._loading = False

    def _on_mapping_changed(self, *_) -> None:
        if not self._loading and self.records:
            self.reparse()

    def _current_profile(self) -> csvio.Profile:
        def value(key: str):
            return self.field_boxes[key].currentData()

        base = self.profile or csvio.detect(self.headers)
        return replace(
            base,
            date=value("date") or "",
            description=value("description") or "",
            amount=value("amount"),
            debit=value("debit"),
            credit=value("credit"),
            category=value("category"),
            kind=value("kind"),
            expense_sign=self.sign_box.currentData(),
        )

    # ---------------------------------------------------------------- preview

    def reparse(self) -> None:
        profile = self._current_profile()
        # A debit column or a direction column both settle the question of which
        # way the money went, leaving the sign convention with nothing to decide.
        self.sign_holder.setVisible(not (profile.debit or profile.kind))

        self.rows = csvio.parse_rows(
            self.records,
            profile,
            fallback_category=self.fallback.currentText(),
            use_issuer_categories=self.use_issuer.isChecked(),
            fingerprints=self.db.fingerprints(),
            income_fingerprints=self.db.income_fingerprints(),
            capture_income=self.capture_income.isChecked(),
        )
        self.format_label.setText(
            f"DETECTED: {(self.profile.label if self.profile else 'unknown').upper()}"
            f"  ·  {len(self.records):,} ROWS"
        )
        self._render_preview()

    def _render_preview(self) -> None:
        currency = self.db.currency
        shown = self.rows[:PREVIEW_LIMIT]

        muted = QColor(self.pal["muted"])
        critical = QColor(self.pal["critical"])
        good = QColor(self.pal["good"])

        with filling(self.table, autosize=(0, 2, 3, 4)):
            self.table.setRowCount(len(shown))
            for r, row in enumerate(shown):
                self._fill_preview_row(r, row, currency, muted, critical, good)
        self._summarise()

    def _fill_preview_row(self, r, row, currency, muted, critical, good) -> None:
        date_text = row.spent_on.isoformat() if row.spent_on else "--"
        cells = [
            QTableWidgetItem(date_text),
            QTableWidgetItem(row.description or "(blank)"),
            QTableWidgetItem(format_cents(row.amount_cents, currency)),
            QTableWidgetItem(row.category or "--"),
            QTableWidgetItem(status_text(row)),
        ]
        cells[2].setTextAlignment(
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        )
        if row.note:
            cells[4].setToolTip(row.note)

        if row.status == "new":
            colour = QColor(self.pal["accent"]) if row.is_income else good
        elif row.status == "error":
            colour = critical
        else:
            colour = muted
        cells[4].setForeground(colour)
        if row.status != "new":
            for cell in cells[:4]:
                cell.setForeground(muted)

        for c, cell in enumerate(cells):
            cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, c, cell)

    def _summarise(self) -> None:
        currency = self.db.currency
        expenses = [r for r in self.rows if r.importable and not r.is_income]
        incomes = [r for r in self.rows if r.importable and r.is_income]
        dupes = sum(1 for r in self.rows if r.status == "duplicate")
        skipped = sum(1 for r in self.rows if r.status == "skipped")
        errors = sum(1 for r in self.rows if r.status == "error")

        parts = []
        if expenses:
            spent = sum(r.amount_cents for r in expenses)
            parts.append(f"{len(expenses):,} expenses ({format_cents(spent, currency)})")
        if incomes:
            earned = sum(r.amount_cents for r in incomes)
            parts.append(f"{len(incomes):,} income ({format_cents(earned, currency)})")
        if not parts:
            parts.append("nothing to import")
        if dupes:
            parts.append(f"{dupes:,} already logged")
        if skipped:
            parts.append(f"{skipped:,} skipped")
        if errors:
            parts.append(f"{errors:,} unreadable")
        if len(self.rows) > PREVIEW_LIMIT:
            parts.append(f"showing the first {PREVIEW_LIMIT:,}")

        total_new = len(expenses) + len(incomes)
        self.summary.setText(" · ".join(parts))
        self.import_button.setEnabled(total_new > 0)
        self.import_button.setText(f"Import {total_new:,}" if total_new else "Import")

    # ----------------------------------------------------------------- action

    def _do_import(self) -> None:
        """Write both halves: money out to expenses, money in to income."""
        expenses = [
            {
                "spent_on": row.spent_on,
                "amount_cents": row.amount_cents,
                "category": row.category or self.fallback.currentText(),
                "description": row.description,
                "notes": "",
            }
            for row in self.rows
            if row.importable and not row.is_income
        ]
        incomes = [
            {
                "received_on": row.spent_on,
                "amount_cents": row.amount_cents,
                "source": row.category or "Other",
                "description": row.description,
                "notes": "",
            }
            for row in self.rows
            if row.importable and row.is_income
        ]

        self.imported_expenses = self.db.add_expenses_bulk(expenses)
        self.imported_income = self.db.add_income_bulk(incomes)
        self.imported = self.imported_expenses + self.imported_income
        self.accept()
