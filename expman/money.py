"""Money helpers.

Amounts are integer cents everywhere below the UI layer. Floats are only ever
produced for display, never stored or summed.
"""
from __future__ import annotations

import re

_CLEAN = re.compile(r"[^0-9.,\-]")


def normalise_decimal(raw: str) -> str:
    """Resolve mixed ',' and '.' grouping into a plain decimal string.

    Both separators are used for both jobs depending on locale, so the rule is:
    whichever appears *last* is the decimal point and the other groups
    thousands. That makes '1,234.56' and '1.234,50' both mean 1234.5, while
    '1,234' stays 1234 and '12,50' becomes 12.50.
    """
    last_dot, last_comma = raw.rfind("."), raw.rfind(",")

    if last_dot >= 0 and last_comma >= 0:
        if last_comma > last_dot:
            return raw.replace(".", "").replace(",", ".")
        return raw.replace(",", "")

    if last_comma >= 0:
        # A lone comma is a decimal point only when it reads like one.
        head, _, tail = raw.rpartition(",")
        if len(tail) in (1, 2) and head:
            return f"{head}.{tail}"
        return raw.replace(",", "")

    return raw


def parse_amount(text: str) -> int:
    """Parse user input into cents. Raises ValueError on anything unusable."""
    raw = _CLEAN.sub("", str(text)).strip()
    if not raw:
        raise ValueError("Enter an amount.")

    raw = normalise_decimal(raw)

    try:
        value = round(float(raw) * 100)
    except ValueError as exc:
        raise ValueError(f"'{text}' is not a valid amount.") from exc

    if value <= 0:
        raise ValueError("Amount must be greater than zero.")
    if value > 10**12:
        raise ValueError("That amount is unreasonably large.")
    return int(value)


def parse_percent(text: str) -> float:
    """Parse a share out of user input. Blank means none at all.

    Not money, but the same two decimal separators are in play, so it borrows
    the rule above rather than growing a second one that could disagree with
    it. A typed '%' is stripped along with everything else that is not a digit.
    """
    text = str(text).strip()
    if not text:
        return 0.0

    # An empty box means no share, but a box with something unusable in it does
    # not: reading "abc" as nothing would save a goal that quietly sets nothing
    # aside, without ever saying so.
    raw = _CLEAN.sub("", text).strip()
    if not raw:
        raise ValueError(f"'{text}' is not a valid percentage.")

    try:
        value = float(normalise_decimal(raw))
    except ValueError as exc:
        raise ValueError(f"'{text}' is not a valid percentage.") from exc

    if value < 0:
        raise ValueError("A share cannot be less than nothing.")
    if value > 100:
        raise ValueError("A share cannot be more than 100%.")
    # Two places is as fine as a share of a payslip ever needs to be, and it
    # keeps 12.5 from arriving as 12.499999999999998.
    return round(value, 2)


def format_cents(cents: int, symbol: str = "$", grouped: bool = True) -> str:
    """Render cents as a currency string, e.g. -1234 -> '-$12.34'."""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(int(cents)), 100)
    body = f"{whole:,}" if grouped else str(whole)
    return f"{sign}{symbol}{body}.{frac:02d}"


# (threshold to abbreviate at, divisor, suffix). The threshold and the divisor
# are deliberately separate: thousands are only worth abbreviating past $10k, but
# they must still be divided by 1,000.
_COMPACT_TIERS = (
    (1_000_000_000, 1_000_000_000, "B"),
    (1_000_000, 1_000_000, "M"),
    (10_000, 1_000, "k"),
)


def format_compact(cents: int, symbol: str = "$") -> str:
    """Shorter form for tight spots like the donut centre: $11.5k, $3.4M."""
    value = abs(cents) / 100
    sign = "-" if cents < 0 else ""
    for threshold, divisor, suffix in _COMPACT_TIERS:
        if value >= threshold:
            return f"{sign}{symbol}{value / divisor:.1f}{suffix}"
    return format_cents(cents, symbol)
