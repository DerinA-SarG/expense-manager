"""Subscriptions page: recurring charges that post themselves to the log."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..dialogs import SubscriptionDialog
from ..money import format_cents
from ..recurrence import label_for, monthly_cents
from ..widgets import (
    Card,
    PageHeader,
    SortItem,
    StatCard,
    align_headers,
    configure_columns,
    filling,
)

COLUMNS = ["Name", "Category", "Cycle", "Next charge", "Per month", "Amount", "Status"]


def _relative(due: date, today: date | None = None) -> str:
    today = today or date.today()
    days = (due - today).days
    if days < 0:
        return f"{-days}d overdue"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days < 31:
        return f"in {days} days"
    months = round(days / 30.4)
    return f"in ~{months} month{'s' if months != 1 else ''}"


class SubscriptionsPage(QWidget):
    def __init__(self, db, palette: dict, on_changed=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.pal = palette
        self.on_changed = on_changed or (lambda: None)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        self.header = PageHeader(
            "Subscriptions",
            "Set a subscription up once — its charges are added to your expense log automatically.",
        )
        add_button = QPushButton("+  Add subscription")
        add_button.setObjectName("Primary")
        add_button.clicked.connect(self.add_subscription)
        self.header.add_action(add_button)
        outer.addWidget(self.header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.stat_monthly = StatCard("Monthly commitment")
        self.stat_yearly = StatCard("Yearly commitment")
        self.stat_next = StatCard("Next charge")
        for card in (self.stat_monthly, self.stat_yearly, self.stat_next):
            stats.addWidget(card)
        outer.addLayout(stats)

        card = Card(padding=0, spacing=0)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self.edit_selected)
        self.table.itemSelectionChanged.connect(self._sync_buttons)

        configure_columns(self.table, stretch=0)
        align_headers(self.table, right={4, 5})

        card.body.addWidget(self.table)
        outer.addWidget(card, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.summary = QLabel("")
        self.summary.setObjectName("Subtle")
        footer.addWidget(self.summary)
        footer.addStretch(1)

        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.toggle_selected)
        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete_selected)
        for button in (self.pause_button, self.edit_button, self.delete_button):
            footer.addWidget(button)
        outer.addLayout(footer)

        QShortcut(QKeySequence("Ctrl+Shift+N"), self, self.add_subscription)

        self.refresh()

    def set_palette(self, palette: dict) -> None:
        self.pal = palette
        self.refresh()

    # ------------------------------------------------------------------ table

    def refresh(self) -> None:
        subs = self.db.list_subscriptions()
        currency = self.db.currency
        today = date.today()

        muted = QColor(self.pal["muted"])
        good = QColor(self.pal["good"])
        warning = QColor(self.pal["warning"])

        with filling(self.table, autosize=range(1, len(COLUMNS))):
            self.table.setRowCount(len(subs))
            for r, sub in enumerate(subs):
                active = bool(sub["active"])
                due = date.fromisoformat(sub["next_due"])
                per_month = monthly_cents(sub["amount_cents"], sub["cycle"])

                name_item = SortItem(sub["name"], sub["name"].lower())
                name_item.setData(Qt.ItemDataRole.UserRole, sub["id"])
                if sub["notes"]:
                    name_item.setToolTip(sub["notes"])

                category_item = SortItem(sub["category"], sub["category"].lower())
                cycle_item = SortItem(label_for(sub["cycle"]), per_month)

                if active:
                    due_text = f"{due.day} {due.strftime('%b %Y')}  ·  {_relative(due, today)}"
                else:
                    due_text = "paused"
                due_item = SortItem(due_text, sub["next_due"] if active else "9999")
                if active and due <= today:
                    due_item.setForeground(warning)
                elif not active:
                    due_item.setForeground(muted)

                month_item = SortItem(format_cents(per_month, currency), per_month)
                month_item.setTextAlignment(
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                )
                amount_item = SortItem(
                    format_cents(sub["amount_cents"], currency), sub["amount_cents"]
                )
                amount_item.setTextAlignment(
                    int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                )

                status_item = SortItem("Active" if active else "Paused", 0 if active else 1)
                status_item.setForeground(good if active else muted)

                for c, item in enumerate(
                    [
                        name_item,
                        category_item,
                        cycle_item,
                        due_item,
                        month_item,
                        amount_item,
                        status_item,
                    ]
                ):
                    if not active and c < 6:
                        item.setForeground(muted)
                    self.table.setItem(r, c, item)


        active_subs = [s for s in subs if s["active"]]
        monthly = sum(monthly_cents(s["amount_cents"], s["cycle"]) for s in active_subs)
        self.stat_monthly.set(
            format_cents(monthly, currency),
            f"{len(active_subs)} active of {len(subs)}",
        )
        self.stat_yearly.set(format_cents(monthly * 12, currency), "at the current rate")

        if active_subs:
            nxt = min(active_subs, key=lambda s: s["next_due"])
            due = date.fromisoformat(nxt["next_due"])
            self.stat_next.set(
                format_cents(nxt["amount_cents"], currency),
                f"{nxt['name']} · {_relative(due, today)}",
            )
        else:
            self.stat_next.set("--", "nothing scheduled")

        self.summary.setText(
            f"{len(subs)} subscription{'s' if len(subs) != 1 else ''}"
            if subs
            else "No subscriptions yet."
        )
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        sub = self._selected()
        self.edit_button.setEnabled(sub is not None)
        self.delete_button.setEnabled(sub is not None)
        self.pause_button.setEnabled(sub is not None)
        self.pause_button.setText(
            "Resume" if sub is not None and not sub["active"] else "Pause"
        )

    def _selected(self):
        model = self.table.selectionModel()
        rows = model.selectedRows() if model else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return None
        return self.db.get_subscription(int(item.data(Qt.ItemDataRole.UserRole)))

    # ---------------------------------------------------------------- actions

    def add_subscription(self) -> None:
        dialog = SubscriptionDialog(self.db.categories(), self.db.currency, parent=self)
        if dialog.exec():
            self.db.add_subscription(**dialog.values())
            posted = self.db.post_due_subscriptions()
            self.refresh()
            self.on_changed()
            if posted:
                self._announce_posted(posted)

    def edit_selected(self) -> None:
        sub = self._selected()
        if sub is None:
            return
        dialog = SubscriptionDialog(
            self.db.categories(), self.db.currency, row=sub, parent=self
        )
        if dialog.exec():
            self.db.update_subscription(sub["id"], **dialog.values())
            posted = self.db.post_due_subscriptions()
            self.refresh()
            self.on_changed()
            if posted:
                self._announce_posted(posted)

    def toggle_selected(self) -> None:
        sub = self._selected()
        if sub is None:
            return
        self.db.set_subscription_active(sub["id"], not sub["active"])
        posted = self.db.post_due_subscriptions()
        self.refresh()
        self.on_changed()
        if posted:
            self._announce_posted(posted)

    def delete_selected(self) -> None:
        sub = self._selected()
        if sub is None:
            return
        posted = self.db.posted_count(sub["id"])

        confirm = QMessageBox(self)
        confirm.setWindowTitle("Delete subscription")
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setText(f"Delete “{sub['name']}”?")

        drop_box = None
        if posted:
            confirm.setInformativeText(
                f"It has posted {posted} charge{'s' if posted != 1 else ''} to your "
                "expense log. Those stay in the log as spending history unless you "
                "tick the box below."
            )
            drop_box = QCheckBox(f"Also delete the {posted} logged charge"
                                 f"{'s' if posted != 1 else ''}")
            confirm.setCheckBox(drop_box)
        else:
            confirm.setInformativeText("It has not posted any charges yet.")

        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)

        if confirm.exec() == QMessageBox.StandardButton.Yes:
            self.db.delete_subscription(
                sub["id"], drop_posted=bool(drop_box and drop_box.isChecked())
            )
            self.refresh()
            self.on_changed()

    def _announce_posted(self, count: int) -> None:
        QMessageBox.information(
            self,
            "Charges posted",
            f"{count} subscription charge{'s' if count != 1 else ''} "
            f"{'were' if count != 1 else 'was'} added to your expense log.",
        )
