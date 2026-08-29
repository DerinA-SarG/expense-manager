"""Goals page: savings targets, each shown as its own progress donut."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..charts import ProgressRing
from ..dialogs import ContributionDialog, GoalDialog
from ..money import format_cents
from ..widgets import Card, EmptyState, PageHeader, StatCard

# How many donuts sit side by side before wrapping.
COLUMNS = 3


class GoalTile(QFrame):
    """One goal: a progress donut over its name and figures."""

    clicked = Signal(int)
    activated = Signal(int)

    def __init__(self, goal: dict, palette: dict, currency: str, parent=None):
        super().__init__(parent)
        self.goal_id = goal["id"]
        self.pal = palette
        self.setObjectName("Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        self.ring = ProgressRing(palette)
        self.ring.setMinimumHeight(158)
        # The tile handles the clicks; a child eating them would break selection.
        self.ring.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.ring)

        self.name = QLabel()
        self.name.setObjectName("EmptyTitle")
        self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name.setWordWrap(True)
        layout.addWidget(self.name)

        self.figures = QLabel()
        self.figures.setObjectName("Subtle")
        self.figures.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.figures)

        self.status = QLabel()
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)

        self.allocation = QLabel()
        self.allocation.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.allocation)

        self.update_from(goal, palette, currency)

    def update_from(self, goal: dict, palette: dict, currency: str) -> None:
        """Refresh in place.

        Tiles are reused rather than rebuilt so that a refresh triggered from a
        tile's own click handler cannot destroy the widget that is still
        handling the event.
        """
        self.goal_id = goal["id"]
        self.pal = palette
        self.ring.set_palette(palette)
        self.ring.set_data(goal["saved_cents"], goal["target_cents"], currency)

        self.name.setText(goal["name"])
        self.figures.setText(
            f"{format_cents(goal['saved_cents'], currency)} of "
            f"{format_cents(goal['target_cents'], currency)}"
        )

        remaining = goal["target_cents"] - goal["saved_cents"]
        if remaining <= 0:
            tail, ink = "Target reached", palette["good"]
        else:
            tail, ink = f"{format_cents(remaining, currency)} to go", palette["muted"]
        self.status.setText(tail)
        self.status.setStyleSheet(f"color: {ink}; font-size: 12px;")

        pct = float(goal["allocation_pct"] or 0)
        if pct > 0:
            self.allocation.setText(f"{pct:g}% of income")
            self.allocation.setStyleSheet(
                f"color: {palette['accent']}; font-size: 11px; font-weight: 600;"
            )
        else:
            self.allocation.setText("Manual only")
            self.allocation.setStyleSheet(
                f"color: {palette['muted']}; font-size: 11px;"
            )
        self.setToolTip(goal["notes"] or "")

    def set_selected(self, selected: bool) -> None:
        border = self.pal["accent"] if selected else self.pal["border"]
        width = 2 if selected else 1
        self.setStyleSheet(
            f"QFrame#Card {{ border: {width}px solid {border}; "
            f"background: {self.pal['surface']}; border-radius: 12px; }}"
        )

    def mousePressEvent(self, event):
        self.clicked.emit(self.goal_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.activated.emit(self.goal_id)
        super().mouseDoubleClickEvent(event)


class GoalsPage(QWidget):
    def __init__(self, db, palette: dict, on_changed=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.pal = palette
        self.on_changed = on_changed or (lambda: None)
        self.selected_id: int | None = None
        self.tiles: dict[int, GoalTile] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        self.header = PageHeader(
            "Goals",
            "Set a share of your income aside automatically, and watch each goal fill up.",
        )
        add_button = QPushButton("+  New goal")
        add_button.setObjectName("Primary")
        add_button.clicked.connect(self.add_goal)
        self.header.add_action(add_button)
        outer.addWidget(self.header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.stat_saved = StatCard("Put aside")
        self.stat_target = StatCard("Total target")
        self.stat_left = StatCard("Still to save")
        self.stat_allocated = StatCard("Set aside from income")
        for card in (self.stat_saved, self.stat_target, self.stat_left, self.stat_allocated):
            stats.addWidget(card)
        outer.addLayout(stats)

        self.grid_host = QWidget()
        self.grid_host.setObjectName("Transparent")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)

        scroll = QScrollArea()
        scroll.setWidget(self.grid_host)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.empty = EmptyState(
            "No savings goals yet",
            "Name something you are saving for, set a target, and choose what "
            "share of each pay packet should go towards it. Every goal gets its "
            "own ring, filling up as income arrives.",
        )
        first = QPushButton("Create your first goal")
        first.setObjectName("Primary")
        first.clicked.connect(self.add_goal)
        self.empty.add_action(first)

        self.stack = QStackedWidget()
        self.stack.setObjectName("Transparent")
        self.stack.addWidget(scroll)
        self.stack.addWidget(self.empty)
        outer.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.summary = QLabel("")
        self.summary.setObjectName("Subtle")
        footer.addWidget(self.summary)
        footer.addStretch(1)
        self.contribute_button = QPushButton("Add money")
        self.contribute_button.setObjectName("Primary")
        self.contribute_button.clicked.connect(self.contribute_to_selected)
        self.edit_button = QPushButton("Edit goal")
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("Danger")
        self.delete_button.clicked.connect(self.delete_selected)
        for button in (self.contribute_button, self.edit_button, self.delete_button):
            footer.addWidget(button)
        outer.addLayout(footer)

        self.refresh()

    # ------------------------------------------------------------------ theme

    def set_palette(self, palette: dict) -> None:
        self.pal = palette
        self.empty.set_palette(palette)
        self.refresh()

    # ----------------------------------------------------------------- render

    def refresh(self) -> None:
        goals = self.db.goals()
        currency = self.db.currency

        if self.selected_id not in {g["id"] for g in goals}:
            self.selected_id = None

        # Reuse tiles wherever the goal still exists; only the surplus is
        # destroyed. Rebuilding the lot would tear down the very widget whose
        # click handler may still be on the stack above this call.
        wanted = {g["id"] for g in goals}
        for goal_id in [g for g in self.tiles if g not in wanted]:
            tile = self.tiles.pop(goal_id)
            self.grid.removeWidget(tile)
            tile.setParent(None)
            tile.deleteLater()

        for index, goal in enumerate(goals):
            tile = self.tiles.get(goal["id"])
            if tile is None:
                tile = GoalTile(goal, self.pal, currency)
                tile.clicked.connect(self._select)
                tile.activated.connect(self._contribute)
                self.tiles[goal["id"]] = tile
            else:
                tile.update_from(goal, self.pal, currency)
            tile.set_selected(goal["id"] == self.selected_id)
            self._place(tile, index // COLUMNS, index % COLUMNS)

        # Keep a trailing stretch so a part-filled last row stays left-aligned
        # instead of the tiles spreading across the width. A grid never forgets
        # a row, so the stretch left behind by a larger set of goals has to be
        # cleared, or a row that now holds tiles would stretch them upright.
        rows = (len(goals) + COLUMNS - 1) // COLUMNS
        for row in range(max(self.grid.rowCount(), rows + 1)):
            self.grid.setRowStretch(row, 0 if row < rows else 1)
        for column in range(COLUMNS):
            self.grid.setColumnStretch(column, 1)

        self.stack.setCurrentIndex(0 if goals else 1)

        saved = sum(g["saved_cents"] for g in goals)
        target = sum(g["target_cents"] for g in goals)
        remaining = max(target - saved, 0)
        reached = [g for g in goals if g["saved_cents"] >= g["target_cents"] > 0]

        self.stat_saved.set(
            format_cents(saved, currency),
            f"{saved / target * 100:.0f}% of everything" if target else "no goals yet",
        )
        self.stat_target.set(
            format_cents(target, currency),
            f"across {len(goals)} goal{'s' if len(goals) != 1 else ''}",
        )
        self.stat_left.set(format_cents(remaining, currency), "still to put aside")

        pct = self.db.total_allocation_pct()
        from_income = sum(g["from_income_cents"] for g in goals)
        note = f"{format_cents(from_income, currency)} so far"
        if pct > 100:
            note += " · over 100%, more than comes in"
        elif not pct:
            note = "no goal takes a share yet"
        self.stat_allocated.set(f"{pct:g}% of income", note)
        self.stat_allocated.value.setStyleSheet(
            f"color: {self.pal['critical']};" if pct > 100 else ""
        )

        contributions = sum(g["contributions"] for g in goals)
        self.summary.setText(
            f"{len(goals)} goal{'s' if len(goals) != 1 else ''} · "
            f"{contributions} contribution{'s' if contributions != 1 else ''}"
            if goals
            else "No goals yet."
        )
        self._sync_buttons()

    def _place(self, tile: GoalTile, row: int, column: int) -> None:
        """Put a tile in its cell, moving it when the ordering has shifted.

        Goals come back sorted by name, so adding one pushes every goal after it
        along a cell. A tile left where it was would end up sharing a cell with
        its new neighbour -- a grid stacks two widgets in one cell rather than
        complaining -- and one of the two goals would disappear from a page that
        still counted it in the footer. Detaching a tile from the layout does not
        destroy it, so a refresh raised from a tile's own click handler is still
        safe.
        """
        at = self.grid.indexOf(tile)
        if at != -1:
            if self.grid.getItemPosition(at)[:2] == (row, column):
                return
            self.grid.removeWidget(tile)
        self.grid.addWidget(tile, row, column)

    def _select(self, goal_id: int) -> None:
        self.selected_id = goal_id
        for gid, tile in self.tiles.items():
            tile.set_selected(gid == goal_id)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has = self.selected_id is not None
        for button in (self.contribute_button, self.edit_button, self.delete_button):
            button.setEnabled(has)

    def _selected_goal(self) -> dict | None:
        if self.selected_id is None:
            return None
        return self.db.get_goal(self.selected_id)

    # ---------------------------------------------------------------- actions

    def _dialog_context(self, exclude_id=None) -> dict:
        """What the goal dialog needs to make a percentage concrete."""
        others = sum(
            float(g["allocation_pct"] or 0)
            for g in self.db.goals()
            if g["id"] != exclude_id
        )
        return {"typical_income": self.db.typical_income(), "other_pct": others}

    def add_goal(self) -> None:
        dialog = GoalDialog(self.db.currency, parent=self, **self._dialog_context())
        if dialog.exec():
            values = dialog.values()
            self.selected_id = self.db.add_goal(**values)
            if values["allocation_pct"] > 0:
                self._resync(f"{values['name']} now takes a share of your income.")
            self.refresh()
            self.on_changed()

    def edit_selected(self) -> None:
        goal = self._selected_goal()
        if goal is None:
            return
        dialog = GoalDialog(
            self.db.currency,
            goal=goal,
            parent=self,
            **self._dialog_context(exclude_id=goal["id"]),
        )
        if dialog.exec():
            values = dialog.values()
            was = float(goal["allocation_pct"] or 0)
            self.db.update_goal(goal["id"], **values)
            if values["allocation_pct"] != was:
                self._announce_share(was, values["allocation_pct"])
            self.refresh()
            self.on_changed()

    def _announce_share(self, was: float, now: float) -> None:
        """Say plainly that the new share starts from here.

        Money already set aside stays set aside at the rate it was set aside at.
        Re-deriving it would mean a goal's progress bar moving because of a
        decision taken today about income banked months ago.
        """
        QMessageBox.information(
            self,
            "Share updated",
            f"New income is now split at {now:g}% instead of {was:g}%."
            "\n\nWhat you have already set aside is unchanged.",
        )

    def _contribute(self, goal_id: int) -> None:
        self.selected_id = goal_id
        # Deferred by one event-loop turn: this arrives from a tile's own
        # double-click handler, and opening a modal dialog straight from there
        # runs a nested loop while that handler is still unwound.
        QTimer.singleShot(0, self.contribute_to_selected)

    def contribute_to_selected(self) -> None:
        goal = self._selected_goal()
        if goal is None:
            return
        dialog = ContributionDialog(goal["name"], self.db.currency, parent=self)
        if dialog.exec():
            self.db.add_contribution(goal["id"], **dialog.values())
            self.refresh()
            self.on_changed()

    def delete_selected(self) -> None:
        goal = self._selected_goal()
        if goal is None:
            return
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Delete goal")
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setText(f"Delete “{goal['name']}”?")
        count = goal["contributions"]
        told = (
            f"Its {count} contribution{'s' if count != 1 else ''} "
            f"({format_cents(goal['saved_cents'], self.db.currency)}) "
            f"{'go' if count != 1 else 'goes'} with it. "
            "This only removes the record of setting the money aside -- your "
            "expenses and income are untouched."
        )

        # Offered only when there is money to move and somewhere to move it to.
        plan = self.db.redistribution_plan(goal["id"])
        move = None
        if plan:
            told += (
                "\n\nOr keep the money: tick the box and it is shared out "
                "between the goals that take a share of income, in the same "
                "proportions they take it in."
            )
            move = QCheckBox(
                f"Put its {format_cents(goal['saved_cents'], self.db.currency)} "
                f"into your other goals"
            )
            move.setToolTip(
                "\n".join(
                    f"{share['name']}  "
                    f"{format_cents(share['cents'], self.db.currency)}"
                    for share in plan
                )
            )
            confirm.setCheckBox(move)
        confirm.setInformativeText(told)
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirm.exec() == QMessageBox.StandardButton.Yes:
            self.db.delete_goal(
                goal["id"], redistribute=bool(move is not None and move.isChecked())
            )
            self.selected_id = None
            self.refresh()
            self.on_changed()
