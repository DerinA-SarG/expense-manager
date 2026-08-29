"""Overview page: where the money went."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..charts import CategoryLegend, DonutChart, Slice
from ..money import format_cents
from ..recurrence import monthly_cents
from ..theme import series_color
from ..widgets import Card, EmptyState, PageHeader, StatCard

# Past this many slices the ring stops being readable, so the tail is folded.
MAX_SLICES = 8

PERIODS = [
    ("This month", "month"),
    ("Last month", "last_month"),
    ("Last 3 months", "quarter"),
    ("Year to date", "ytd"),
    ("All time", "all"),
]


def period_range(key: str, today: date | None = None) -> tuple[date | None, date | None]:
    today = today or date.today()
    if key == "month":
        return today.replace(day=1), today
    if key == "last_month":
        last_day_prev = today.replace(day=1) - timedelta(days=1)
        return last_day_prev.replace(day=1), last_day_prev
    if key == "quarter":
        month = today.month - 2
        year = today.year
        if month <= 0:
            month += 12
            year -= 1
        return date(year, month, 1), today
    if key == "ytd":
        return date(today.year, 1, 1), today
    return None, None


class OverviewPage(QWidget):
    def __init__(self, db, palette: dict, on_add_expense=None, on_add_subscription=None,
                 parent=None):
        super().__init__(parent)
        self.db = db
        self.pal = palette

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        self.header = PageHeader("Overview", "")
        self.period_box = QComboBox()
        for label, key in PERIODS:
            self.period_box.addItem(label, key)
        self.period_box.setCurrentIndex(0)
        self.period_box.setMinimumWidth(150)
        self.period_box.currentIndexChanged.connect(self.refresh)
        self.header.add_action(self.period_box)
        outer.addWidget(self.header)

        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.stat_total = StatCard("Total spent")
        self.stat_income = StatCard("Income")
        self.stat_net = StatCard("Net")
        self.stat_pace = StatCard("Average per day")
        self.stat_subs = StatCard("Subscriptions")
        for card in (
            self.stat_total,
            self.stat_income,
            self.stat_net,
            self.stat_pace,
            self.stat_subs,
        ):
            stats.addWidget(card)
        outer.addLayout(stats)

        chart_card = Card(padding=20, spacing=14)
        title = QLabel("Spending by category")
        title.setObjectName("StatLabel")
        chart_card.body.addWidget(title)

        split = QHBoxLayout()
        split.setSpacing(24)

        self.donut = DonutChart(self.pal)
        split.addWidget(self.donut, 5)

        self.legend = CategoryLegend(self.pal)
        scroll = QScrollArea()
        scroll.setWidget(self.legend)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(300)
        split.addWidget(scroll, 4)

        chart = QWidget()
        chart.setObjectName("Transparent")
        chart.setLayout(split)

        self.empty = EmptyState(
            "No expenses in this period",
            "Log a one-off expense, or add a subscription and its charges will be "
            "posted here for you every billing cycle.",
        )
        if on_add_expense:
            add_expense = QPushButton("Add an expense")
            add_expense.setObjectName("Primary")
            add_expense.clicked.connect(on_add_expense)
            self.empty.add_action(add_expense)
        if on_add_subscription:
            add_sub = QPushButton("Add a subscription")
            add_sub.clicked.connect(on_add_subscription)
            self.empty.add_action(add_sub)

        self.chart_stack = QStackedWidget()
        self.chart_stack.setObjectName("Transparent")
        self.chart_stack.addWidget(chart)
        self.chart_stack.addWidget(self.empty)

        chart_card.body.addWidget(self.chart_stack)
        outer.addWidget(chart_card, 1)

        # Hovering either view highlights the same category in both.
        self.donut.hoverChanged.connect(self.legend.set_hover)
        self.legend.hoverChanged.connect(self.donut.set_hover)

        # Overview is the page you land on, so it has to arrive populated. Every
        # other page refreshes in its own constructor; this one used to rely on
        # navigation, which never happens before it is first seen.
        self.refresh()

    # ------------------------------------------------------------------ theme

    def set_palette(self, palette: dict) -> None:
        self.pal = palette
        self.donut.set_palette(palette)
        self.legend.set_palette(palette)
        self.empty.set_palette(palette)
        self.refresh()

    # ----------------------------------------------------------------- render

    def refresh(self) -> None:
        key = self.period_box.currentData()
        start, end = period_range(key)
        currency = self.db.currency

        totals = self.db.category_totals(start, end)
        total_cents = sum(amount for _, amount in totals)

        slices = self._build_slices(totals)
        plural = "y" if len(totals) == 1 else "ies"
        self.donut.set_data(
            slices,
            currency,
            caption="Total spent",
            subcaption=f"{len(totals)} categor{plural}",
        )
        self.legend.set_data(slices, currency)
        self.chart_stack.setCurrentIndex(0 if totals else 1)

        rows = self.db.list_expenses(start, end)
        self.stat_total.set(
            format_cents(total_cents, currency),
            f"{len(rows):,} transaction{'s' if len(rows) != 1 else ''}"
            f" · {len(totals)} categor{'y' if len(totals) == 1 else 'ies'}",
        )

        income = self.db.income_total(start, end)
        net = income - total_cents
        self.stat_income.set(income and format_cents(income, currency) or "--",
                             self._range_label(start, end) if income else "none logged")
        self.stat_net.set(
            format_cents(net, currency),
            "kept this period" if net >= 0 else "spent beyond income",
        )
        # Net is the one figure whose sign changes its meaning, so it is the one
        # that earns colour -- and the caption says which way regardless.
        self.stat_net.value.setStyleSheet(
            f"color: {self.pal['good'] if net >= 0 else self.pal['critical']};"
        )

        days = self._day_count(start, end)
        per_day = round(total_cents / days) if days else 0
        self.stat_pace.set(
            format_cents(per_day, currency),
            f"over {days} day{'s' if days != 1 else ''}" if total_cents else "nothing logged yet",
        )

        subs = self.db.list_subscriptions(active_only=True)
        monthly = sum(monthly_cents(s["amount_cents"], s["cycle"]) for s in subs)
        self.stat_subs.set(
            format_cents(monthly, currency) + " /mo",
            f"{len(subs)} active"
            + (f" · {format_cents(monthly * 12, currency)}/yr" if subs else ""),
        )

        self.header.set_subtitle(self._subtitle(start, end, total_cents, currency))

    def _build_slices(self, totals: list[tuple[str, int]]) -> list[Slice]:
        """Fixed-order hues for the leaders; everything past the ramp folds into
        one neutral bucket rather than inventing a ninth colour."""
        if len(totals) <= MAX_SLICES:
            return [
                Slice(name, amount, series_color(self.pal, i))
                for i, (name, amount) in enumerate(totals)
            ]

        head = totals[: MAX_SLICES - 1]
        tail = totals[MAX_SLICES - 1 :]
        slices = [
            Slice(name, amount, series_color(self.pal, i))
            for i, (name, amount) in enumerate(head)
        ]
        slices.append(
            Slice(
                f"Other ({len(tail)} categories)",
                sum(amount for _, amount in tail),
                self.pal["other"],
            )
        )
        return slices

    def _day_count(self, start: date | None, end: date | None) -> int:
        if start is None:
            span = self.db.expense_span()
            if not span:
                return 0
            start, end = span
        end = end or date.today()
        return max((end - start).days + 1, 1)

    @staticmethod
    def _range_label(start: date | None, end: date | None) -> str:
        # strftime day padding differs between platforms, so days are formatted by hand.
        if start is None:
            return "all recorded expenses"
        end = end or date.today()
        if start.year == end.year and start.month == end.month:
            whole_month = start.day == 1 and end.day == calendar.monthrange(end.year, end.month)[1]
            if whole_month:
                return start.strftime("%B %Y")
            return f"{start.day}–{end.day} {end.strftime('%b %Y')}"
        return f"{start.day} {start.strftime('%b %Y')} – {end.day} {end.strftime('%b %Y')}"

    def _subtitle(self, start, end, total_cents: int, currency: str) -> str:
        if total_cents == 0:
            return "Nothing logged for this period yet — add an expense to get started."
        return f"{format_cents(total_cents, currency)} spent in {self._range_label(start, end)}."
