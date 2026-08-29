"""Billing-cycle maths for subscriptions."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

# cycle key -> (label, occurrences per year)
CYCLES: dict[str, tuple[str, int]] = {
    "weekly": ("Weekly", 52),
    "biweekly": ("Every 2 weeks", 26),
    "monthly": ("Monthly", 12),
    "quarterly": ("Quarterly", 4),
    "semiannual": ("Every 6 months", 2),
    "yearly": ("Yearly", 1),
}

_MONTH_STEP = {"monthly": 1, "quarterly": 3, "semiannual": 6, "yearly": 12}


def label_for(cycle: str) -> str:
    return CYCLES.get(cycle, (cycle.title(), 12))[0]


def per_year(cycle: str) -> int:
    return CYCLES.get(cycle, ("", 12))[1]


def add_months(d: date, months: int, anchor_day: int | None = None) -> date:
    """Add whole months, clamping to the end of the target month.

    ``anchor_day`` is the day-of-month the subscription really bills on. Passing
    it prevents drift: a 31st subscription lands on Feb 28 and then goes back to
    Mar 31, rather than sticking at 28 forever.
    """
    day = anchor_day or d.day
    total = (d.year * 12 + d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def advance(d: date, cycle: str, anchor_day: int | None = None) -> date:
    """Return the billing date after ``d`` for the given cycle."""
    if cycle == "weekly":
        return d + timedelta(days=7)
    if cycle == "biweekly":
        return d + timedelta(days=14)
    step = _MONTH_STEP.get(cycle)
    if step is None:
        raise ValueError(f"Unknown billing cycle: {cycle!r}")
    return add_months(d, step, anchor_day)


def annual_cents(amount_cents: int, cycle: str) -> int:
    return int(amount_cents) * per_year(cycle)


def monthly_cents(amount_cents: int, cycle: str) -> int:
    """Normalised monthly cost, for comparing cycles against each other."""
    return round(annual_cents(amount_cents, cycle) / 12)
