"""Goals page: savings targets, each shown as its own progress donut.

Money reaches a goal only because someone put it there. Income logged elsewhere
in the app leaves a share *waiting*, the banner at the top says exactly what
that share works out to and where it would land, and the goals move when the
button is pressed. The figures on this page and the figures that get written are
the same plan -- see `Database.pending_plan`.
"""
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

# Goals named individually in a banner before it gives up and counts them.
NAMED_SHARES = 3


class ActionBanner(Card):
    """A strip above the goals saying what is waiting, and offering to do it.

    Hidden unless it has something to say. Everything it offers is described in
    full before it happens: this is the one place in the app where pressing a
    button moves money between goals.
    """

    def __init__(self, parent=None):
        super().__init__(parent, padding=14, spacing=4)

        row = QHBoxLayout()
        row.setSpacing(12)

        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = QLabel("")
        self.title.setObjectName("EmptyTitle")
        self.detail = QLabel("")
        self.detail.setObjectName("Subtle")
        self.detail.setWordWrap(True)
        text.addWidget(self.title)
        text.addWidget(self.detail)
        row.addLayout(text, 1)

        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(8)
        self.buttons.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        row.addLayout(self.buttons)

        self.body.addLayout(row)
        self.setVisible(False)

    def add_button(self, label: str, primary: bool = False) -> QPushButton:
        button = QPushButton(label)
        if primary:
            button.setObjectName("Primary")
        self.buttons.addWidget(button)
        return button

    def set(self, title: str, detail: str) -> None:
        self.title.setText(title)
        self.detail.setText(detail)


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

    def update_from(
        self, goal: dict, palette: dict, currency: str, waiting: int = 0
    ) -> None:
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
        if remaining < 0:
            # Over target. Not an error -- money was put here by hand, or the
            # target moved -- but it is the thing the banner is offering to fix,
            # so the tile says so in the same words.
            tail = f"{format_cents(-remaining, currency)} over target"
            ink = palette["warning"]
        elif remaining == 0:
            tail, ink = "Target reached", palette["good"]
        else:
            tail, ink = f"{format_cents(remaining, currency)} to go", palette["muted"]
        self.status.setText(tail)
        self.status.setStyleSheet(f"color: {ink}; font-size: 12px;")

        pct = float(goal["allocation_pct"] or 0)
        if waiting:
            # What this goal would be given if the goals were updated now. It is
            # a plan, not a balance, so it never joins the figures above it.
            self.allocation.setText(
                f"+{format_cents(waiting, currency)} waiting"
                + (f" · {pct:g}% of income" if pct > 0 else "")
            )
            self.allocation.setStyleSheet(
                f"color: {palette['accent']}; font-size: 11px; font-weight: 600;"
            )
        elif pct > 0:
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
    def __init__(self, db, palette: dict, on_changed=None, on_step=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.pal = palette
        self.on_changed = on_changed or (lambda: None)
        # Ticks "Update Goals" off the panel in the sidebar, and only where
        # money actually moved.
        self.on_step = on_step or (lambda key: None)
        self.selected_id: int | None = None
        self.tiles: dict[int, GoalTile] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)

        self.header = PageHeader(
            "Goals",
            "Work out what each goal is owed from your income, then set it aside "
            "when you are ready.",
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
        self.stat_waiting = StatCard("Waiting to be set aside")
        for card in (self.stat_saved, self.stat_target, self.stat_left, self.stat_waiting):
            stats.addWidget(card)
        outer.addLayout(stats)

        self.pending_banner = ActionBanner()
        self.apply_button = self.pending_banner.add_button("Update goals", primary=True)
        self.apply_button.setToolTip("Set the amounts above aside now")
        self.apply_button.clicked.connect(self.apply_pending)
        self.skip_button = self.pending_banner.add_button("Skip")
        self.skip_button.setToolTip(
            "Leave this income out: nothing is set aside and it stops being offered"
        )
        self.skip_button.clicked.connect(self.skip_pending)
        outer.addWidget(self.pending_banner)

        self.excess_banner = ActionBanner()
        self.settle_button = self.excess_banner.add_button("Share it out", primary=True)
        self.settle_button.setToolTip(
            "Move what is above target into the goals that still have room"
        )
        self.settle_button.clicked.connect(self.settle_excess)
        outer.addWidget(self.excess_banner)

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
            "own ring, and fills up when you set the money aside.",
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
        plan = self.db.pending_plan()
        excess = self.db.excess_plan()

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
            waiting = plan["by_goal"].get(goal["id"], 0)
            tile = self.tiles.get(goal["id"])
            if tile is None:
                tile = GoalTile(goal, self.pal, currency)
                tile.update_from(goal, self.pal, currency, waiting)
                tile.clicked.connect(self._select)
                tile.activated.connect(self._contribute)
                self.tiles[goal["id"]] = tile
            else:
                tile.update_from(goal, self.pal, currency, waiting)
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

        self.stat_saved.set(
            format_cents(saved, currency),
            f"{saved / target * 100:.0f}% of everything" if target else "no goals yet",
        )
        self.stat_target.set(
            format_cents(target, currency),
            f"across {len(goals)} goal{'s' if len(goals) != 1 else ''}",
        )
        self.stat_left.set(format_cents(remaining, currency), "still to put aside")
        self._show_waiting(plan, goals, currency)
        self._show_pending_banner(plan, currency)
        self._show_excess_banner(excess, currency)

        contributions = sum(g["contributions"] for g in goals)
        self.summary.setText(
            f"{len(goals)} goal{'s' if len(goals) != 1 else ''} · "
            f"{contributions} contribution{'s' if contributions != 1 else ''}"
            if goals
            else "No goals yet."
        )
        self._sync_buttons()

    def _show_waiting(self, plan: dict, goals: list[dict], currency: str) -> None:
        """The headline figure for money worked out but not yet set aside."""
        pct = self.db.total_allocation_pct()
        if plan["total_cents"]:
            note = (
                f"from {plan['count']} income "
                f"{'entry' if plan['count'] == 1 else 'entries'}"
            )
        elif not pct:
            note = "no goal takes a share yet"
        elif pct > 100:
            note = f"goals claim {pct:g}% of income, more than comes in"
        else:
            from_income = sum(g["from_income_cents"] for g in goals)
            note = f"{format_cents(from_income, currency)} set aside so far"
        self.stat_waiting.set(format_cents(plan["total_cents"], currency), note)
        self.stat_waiting.value.setStyleSheet(
            f"color: {self.pal['accent']};" if plan["total_cents"] else ""
        )

    def _share_list(self, shares: list[dict], currency: str) -> str:
        named = [
            f"{share['name']} {format_cents(share['cents'], currency)}"
            for share in shares[:NAMED_SHARES]
        ]
        rest = len(shares) - len(named)
        if rest > 0:
            named.append(f"and {rest} more")
        return " · ".join(named)

    def _show_pending_banner(self, plan: dict, currency: str) -> None:
        """Say what updating the goals would do, before it is done."""
        if not plan["count"] or not (plan["total_cents"] or plan["unplaced_cents"]):
            self.pending_banner.setVisible(False)
            return

        entries = (
            f"{plan['count']} income "
            f"{'entry' if plan['count'] == 1 else 'entries'} "
            f"({format_cents(plan['income_cents'], currency)})"
        )
        detail = f"From {entries}. " + self._share_list(plan["shares"], currency)
        if plan["unplaced_cents"]:
            detail += (
                f". {format_cents(plan['unplaced_cents'], currency)} stays where "
                "it is -- every goal that takes a share is full."
            )
        self.pending_banner.set(
            f"{format_cents(plan['total_cents'], currency)} ready to set aside",
            detail,
        )
        self.apply_button.setEnabled(bool(plan["total_cents"]))
        self.pending_banner.setVisible(True)

    def _show_excess_banner(self, excess: dict, currency: str) -> None:
        """Offer to put money sitting above a target back to work."""
        if not excess["moves"]:
            self.excess_banner.setVisible(False)
            return

        over = excess["over"]
        who = ", ".join(move["name"] for move in excess["moves"])
        shares: dict[int, dict] = {}
        for move in excess["moves"]:
            for share in move["shares"]:
                landing = shares.setdefault(
                    share["id"], {"name": share["name"], "cents": 0}
                )
                landing["cents"] += share["cents"]
        ordered = sorted(shares.values(), key=lambda s: -s["cents"])

        detail = (
            f"{who} {'is' if len(excess['moves']) == 1 else 'are'} holding more "
            "than the target. Sharing it out sends it to the goals with room, in "
            "proportion to the share of income each takes: "
            + self._share_list(ordered, currency)
            + "."
        )
        stuck = sum(move["stuck_cents"] for move in excess["moves"])
        if stuck:
            detail += (
                f" {format_cents(stuck, currency)} stays put -- there is nowhere "
                "with room for it."
            )
        self.excess_banner.set(
            f"{format_cents(excess['excess_cents'], currency)} is above target "
            f"in {len(over)} goal{'s' if len(over) != 1 else ''}",
            detail,
        )
        self.excess_banner.setVisible(True)

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

    # -------------------------------------------------- money waiting to land

    def apply_pending(self) -> None:
        """Set aside what the banner said, and say what happened."""
        plan = self.db.apply_pending()
        self.refresh()
        self.on_changed()
        if not plan["total_cents"]:
            return
        self.on_step("goals")

        currency = self.db.currency
        lines = "\n".join(
            f"  {share['name']}   {format_cents(share['cents'], currency)}"
            for share in plan["shares"]
        )
        told = (
            f"{format_cents(plan['total_cents'], currency)} set aside across "
            f"{len(plan['shares'])} goal{'s' if len(plan['shares']) != 1 else ''}:"
            f"\n\n{lines}"
        )
        if plan["unplaced_cents"]:
            told += (
                f"\n\n{format_cents(plan['unplaced_cents'], currency)} was not set "
                "aside: every goal that takes a share of income is full."
            )
        QMessageBox.information(self, "Goals updated", told)

    def skip_pending(self) -> None:
        """Take waiting income out of the queue without setting anything aside."""
        plan = self.db.pending_plan()
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Skip this income")
        confirm.setIcon(QMessageBox.Icon.Question)
        confirm.setText(
            f"Leave {format_cents(plan['total_cents'], self.db.currency)} out of "
            "your goals?"
        )
        confirm.setInformativeText(
            f"The {plan['count']} income "
            f"{'entry stays' if plan['count'] == 1 else 'entries stay'} on the "
            "Income page exactly as logged. This only stops the share being "
            "offered again, and it cannot be undone from here -- you would have "
            "to add the money to each goal by hand."
        )
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        confirm.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirm.exec() == QMessageBox.StandardButton.Yes:
            self.db.skip_pending()
            self.refresh()
            self.on_changed()

    def settle_excess(self) -> None:
        """Move what is over target into the goals that still have room."""
        plan = self.db.excess_plan()
        if not plan["moves"]:
            return
        currency = self.db.currency
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Share out what is over target")
        confirm.setIcon(QMessageBox.Icon.Question)
        confirm.setText(
            f"Move {format_cents(plan['total_cents'], currency)} into the goals "
            "with room?"
        )
        detail = []
        for move in plan["moves"]:
            where = ", ".join(
                f"{share['name']} {format_cents(share['cents'], currency)}"
                for share in move["shares"]
            )
            detail.append(
                f"{move['name']}: {format_cents(move['cents'], currency)} -> {where}"
            )
        confirm.setInformativeText(
            "\n".join(detail)
            + "\n\nEach goal keeps exactly its target. Nothing on the Expenses or "
            "Income pages changes -- this only moves money between goals."
        )
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        confirm.setDefaultButton(QMessageBox.StandardButton.Yes)
        if confirm.exec() == QMessageBox.StandardButton.Yes:
            self.db.settle_excess()
            self.refresh()
            self.on_changed()
            self.on_step("goals")

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
            self.refresh()
            self.on_changed()

    def edit_selected(self) -> None:
        goal = self._selected_goal()
        if goal is None:
            return
        dialog = GoalDialog(
            self.db.currency,
            goal=goal,
            reset_plan=self.db.redistribution_plan(goal["id"]),
            parent=self,
            **self._dialog_context(exclude_id=goal["id"]),
        )
        if not dialog.exec():
            return

        values = dialog.values()
        was = float(goal["allocation_pct"] or 0)
        # Cleared first, while the goal still holds the share it was saved
        # under: where the money goes is a question about the old settings, not
        # the ones being saved in the same breath.
        if dialog.reset:
            self.db.reset_goal(goal["id"], redistribute=dialog.reset_redistribute)
            if dialog.reset_redistribute:
                self.on_step("goals")
        self.db.update_goal(goal["id"], **values)
        self.refresh()
        self.on_changed()
        if dialog.reset:
            self._announce_reset(goal, dialog)
        elif values["allocation_pct"] != was:
            self._announce_share(was, values["allocation_pct"])

    def _announce_reset(self, goal: dict, dialog) -> None:
        currency = self.db.currency
        held = format_cents(goal["saved_cents"], currency)
        if not dialog.reset_redistribute:
            told = f"{held} was cleared. The goal, its target and its share stay."
        else:
            moved = sum(share["cents"] for share in dialog.reset_plan)
            where = ", ".join(share["name"] for share in dialog.reset_plan)
            told = f"{format_cents(moved, currency)} moved to {where}."
            left = goal["saved_cents"] - moved
            if left > 0:
                told += (
                    f" The remaining {format_cents(left, currency)} had nowhere "
                    "to go and was cleared."
                )
        QMessageBox.information(self, f"{goal['name']} reset", told)

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
            "\n\nWhat you have already set aside is unchanged, and income still "
            "waiting to be applied is recalculated at the new share.",
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
        dialog = ContributionDialog(
            goal["name"],
            self.db.currency,
            plan=lambda cents: self.db.contribution_plan(goal["id"], cents),
            parent=self,
        )
        if dialog.exec():
            # `contribute` rather than `add_contribution`: what will not fit
            # flows on to the goals with room, exactly as the dialog said it
            # would while the amount was being typed.
            self.db.contribute(goal["id"], **dialog.values())
            self.refresh()
            self.on_changed()
            self.on_step("goals")

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
            moved = sum(share["cents"] for share in plan)
            told += (
                "\n\nOr keep the money: tick the box and it is shared out "
                "between the goals that take a share of income and still have "
                "room, in the same proportions they take it in."
            )
            stuck = goal["saved_cents"] - moved
            if stuck > 0:
                told += (
                    f" Only {format_cents(moved, self.db.currency)} of it fits; "
                    f"the other {format_cents(stuck, self.db.currency)} goes with "
                    "the goal."
                )
            move = QCheckBox(
                f"Put its {format_cents(moved, self.db.currency)} "
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
