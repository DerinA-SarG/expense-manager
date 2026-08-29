"""CSV import and export.

Every card issuer exports a slightly different shape and none of them promise to
keep it stable, so the profiles below are a *starting guess*: detection picks the
closest match and the import dialog always lets you correct the column mapping
before anything is written.

Three shapes cover the common cases:

* one signed amount column (Discover) -- purchases positive, payments negative;
* separate debit and credit columns (Capital One credit cards);
* an unsigned amount plus a Debit/Credit column (Capital One deposit accounts).

Credits become income rather than expenses. Folding them into the spending log
as negative amounts would corrupt the chart, so each row is classified by
direction and routed to the right table.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .money import normalise_decimal

# ---------------------------------------------------------------- amount / date

_MONEY_STRIP = re.compile(r"[^0-9.,()\-+]")

DATE_FORMATS = (
    "%m/%d/%Y",
    "%Y-%m-%d",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%m-%d-%Y",
    "%d-%b-%Y",
    "%b %d, %Y",
    "%Y/%m/%d",
)


def parse_date(text: str) -> date | None:
    text = (text or "").strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_signed_money(text: str) -> int | None:
    """Parse a statement amount into signed cents, or None if unusable.

    Unlike the amount field in the add-expense form this accepts negatives and
    zero: a statement legitimately contains payments and refunds, and the caller
    decides what to do with them.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    negative = False
    # Accounting style: (12.34) means -12.34
    if raw.startswith("(") and raw.endswith(")"):
        negative = True
        raw = raw[1:-1]

    raw = _MONEY_STRIP.sub("", raw).replace("(", "").replace(")", "")
    if raw.startswith("-"):
        negative = True
    raw = raw.lstrip("+-")

    raw = normalise_decimal(raw)

    if not raw:
        return None
    try:
        cents = round(float(raw) * 100)
    except ValueError:
        return None
    return -cents if negative else cents


# ----------------------------------------------------------------- header names


def normalise(header: str) -> str:
    """Fold a header to a comparable key: 'Trans. Date' -> 'trans date'."""
    text = (header or "").strip().lower().replace(".", " ").replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


# -------------------------------------------------------------------- profiles


# Values in a direction column that mean money leaving the account.
DEBIT_WORDS = ("debit", "withdrawal", "purchase", "payment", "sale", "charge")


@dataclass
class Profile:
    key: str
    label: str
    required: tuple[str, ...]
    date: str
    description: str
    amount: str | None = None
    debit: str | None = None
    credit: str | None = None
    category: str | None = None
    # A column naming the direction ("Debit"/"Credit") alongside an unsigned
    # amount -- how Capital One's deposit-account export encodes it.
    kind: str | None = None
    # +1: a positive amount is money spent. -1: a negative amount is money spent.
    # Ignored when `kind` is in play, since then the amount carries no sign.
    expense_sign: int = 1

    def matches(self, headers: set[str]) -> bool:
        return all(name in headers for name in self.required)


PROFILES: tuple[Profile, ...] = (
    Profile(
        key="discover",
        label="Discover card",
        required=("trans date", "description", "amount"),
        date="trans date",
        description="description",
        amount="amount",
        category="category",
        expense_sign=1,  # Discover shows purchases positive, payments negative
    ),
    Profile(
        key="capitalone_credit",
        label="Capital One credit card",
        required=("transaction date", "description", "debit"),
        date="transaction date",
        description="description",
        debit="debit",
        credit="credit",
        category="category",
    ),
    Profile(
        key="capitalone_bank",
        label="Capital One bank account",
        required=(
            "transaction date",
            "transaction description",
            "transaction amount",
            "transaction type",
        ),
        date="transaction date",
        description="transaction description",
        amount="transaction amount",
        # Amounts here are unsigned -- a $21.35 purchase and a $246.03 deposit
        # both read "21.35"/"246.03". Only this column says which way the money
        # went, so the sign convention must not be used.
        kind="transaction type",
    ),
    Profile(
        key="expman",
        label="Expense Manager export",
        required=("date", "amount", "category", "description"),
        date="date",
        description="description",
        amount="amount",
        category="category",
        expense_sign=1,
    ),
)

# Fields a generic file might plausibly use, best guess first.
_GUESS = {
    "date": ("date", "transaction date", "trans date", "posted date", "post date"),
    "description": ("description", "transaction description", "merchant", "name", "payee", "memo"),
    "amount": ("amount", "transaction amount", "value"),
    "debit": ("debit", "withdrawal", "charges"),
    "credit": ("credit", "deposit", "payments"),
    "category": ("category",),
    "kind": ("transaction type", "type", "debit/credit", "direction"),
}


def detect(headers: list[str]) -> Profile:
    """Pick the closest known profile, falling back to a guess by column name."""
    keys = {normalise(h) for h in headers}
    for profile in PROFILES:
        if profile.matches(keys):
            return profile

    def first(names) -> str | None:
        return next((n for n in names if n in keys), None)

    debit, credit = first(_GUESS["debit"]), first(_GUESS["credit"])
    return Profile(
        key="generic",
        label="Unrecognised layout",
        required=(),
        date=first(_GUESS["date"]) or "",
        description=first(_GUESS["description"]) or "",
        amount=None if debit else first(_GUESS["amount"]),
        debit=debit,
        credit=credit,
        category=first(_GUESS["category"]),
        kind=first(_GUESS["kind"]),
        expense_sign=1,
    )


# ------------------------------------------------------- issuer category naming

ISSUER_CATEGORIES = {
    "restaurants": "Dining",
    "dining": "Dining",
    "food & drink": "Dining",
    "bars & cafes": "Dining",
    "supermarkets": "Groceries",
    "grocery": "Groceries",
    "groceries": "Groceries",
    "warehouse clubs": "Groceries",
    "gasoline": "Transport",
    "gas/automotive": "Transport",
    "gas": "Transport",
    "automotive": "Transport",
    "travel": "Transport",
    "airfare": "Transport",
    "airlines": "Transport",
    "car rental": "Transport",
    "other travel": "Transport",
    "merchandise": "Shopping",
    "shopping": "Shopping",
    "department stores": "Shopping",
    "home improvement": "Shopping",
    "home": "Shopping",
    "medical services": "Health",
    "health care": "Health",
    "medical": "Health",
    "entertainment": "Entertainment",
    "services": "Other",
    "professional services": "Other",
    "government services": "Other",
    "education": "Other",
    "insurance": "Other",
    "utilities": "Utilities",
    "phone/cable": "Utilities",
    "internet": "Utilities",
    "fee/interest charge": "Other",
    "fee": "Other",
    "interest": "Other",
}

# Rows whose issuer category says outright that this is not spending.
CREDIT_CATEGORIES = {
    "payment",
    "payment/credit",
    "payments and credits",
    "awards and rebate credits",
    "credit",
    "refund",
}


def map_category(issuer_value: str, fallback: str) -> str:
    key = (issuer_value or "").strip().lower()
    if not key:
        return fallback
    return ISSUER_CATEGORIES.get(key, issuer_value.strip())


# Statement descriptions rarely carry an income category, but they do say enough
# in words to beat filing every deposit under "Other".
INCOME_HINTS = (
    ("payroll", "Salary"),
    ("direct dep", "Salary"),
    ("salary", "Salary"),
    ("paycheck", "Salary"),
    ("interest", "Interest"),
    ("dividend", "Interest"),
    ("refund", "Refund"),
    ("return", "Refund"),
    ("cashback", "Refund"),
    ("rebate", "Refund"),
    ("transfer from", "Transfer in"),
    ("from savings", "Transfer in"),
    ("deposit from", "Transfer in"),
    ("zelle from", "Gift"),
    ("venmo from", "Gift"),
)


def guess_income_source(description: str, fallback: str = "Other") -> str:
    text = (description or "").lower()
    for needle, source in INCOME_HINTS:
        if needle in text:
            return source
    return fallback


# ---------------------------------------------------------------------- reading


@dataclass
class ParsedRow:
    spent_on: date | None
    amount_cents: int
    description: str
    category: str
    status: str  # new | duplicate | skipped | error
    note: str = ""
    kind: str = "expense"  # expense | income

    @property
    def importable(self) -> bool:
        return self.status == "new"

    @property
    def is_income(self) -> bool:
        return self.kind == "income"


@dataclass
class ImportResult:
    headers: list[str]
    profile: Profile
    rows: list[ParsedRow] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for r in self.rows if r.status == status)

    @property
    def importable(self) -> list[ParsedRow]:
        return [r for r in self.rows if r.importable]

    @property
    def expenses(self) -> list[ParsedRow]:
        return [r for r in self.rows if r.importable and not r.is_income]

    @property
    def incomes(self) -> list[ParsedRow]:
        return [r for r in self.rows if r.importable and r.is_income]


def read_table(path: str | Path) -> tuple[list[str], list[dict]]:
    """Read a CSV into headers plus dict rows, tolerating BOMs and odd delimiters."""
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")

    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return [], []

    headers = [h.strip() for h in rows[0]]
    records = []
    for row in rows[1:]:
        # Statement footers are often short rows; pad rather than drop them so
        # they surface in the preview as errors the user can see.
        padded = list(row) + [""] * (len(headers) - len(row))
        records.append(dict(zip(headers, padded)))
    return headers, records


def parse_rows(
    records: list[dict],
    profile: Profile,
    fallback_category: str = "Other",
    use_issuer_categories: bool = True,
    fingerprints: set[tuple[str, int, str]] | None = None,
    income_fingerprints: set[tuple[str, int, str]] | None = None,
    capture_income: bool = True,
    fallback_income_source: str = "Other",
) -> list[ParsedRow]:
    """Turn raw CSV records into rows ready for review.

    Every row is reduced to one signed number first -- positive is money out,
    negative is money in -- regardless of which of the three layouts encoded it.
    Classification then happens in one place instead of once per layout.
    """
    fingerprints = fingerprints or set()
    income_fingerprints = income_fingerprints or set()
    seen_out: set[tuple[str, int, str]] = set()
    seen_in: set[tuple[str, int, str]] = set()
    out: list[ParsedRow] = []

    lookup = {normalise(k): k for k in (records[0].keys() if records else [])}

    def cell(record: dict, key: str | None) -> str:
        if not key:
            return ""
        actual = lookup.get(normalise(key))
        return (record.get(actual, "") if actual else "").strip()

    for record in records:
        when = parse_date(cell(record, profile.date))
        description = cell(record, profile.description)
        issuer_category = cell(record, profile.category)
        kind_value = cell(record, profile.kind).strip().lower() if profile.kind else ""

        # ---- reduce the layout to one signed amount ------------------------
        amount: int | None
        if profile.debit:
            debit = parse_signed_money(cell(record, profile.debit))
            credit = parse_signed_money(cell(record, profile.credit))
            # Capital One leaves Debit empty on a payment row and fills Credit.
            amount = -abs(credit) if debit is None and credit is not None else debit
        elif kind_value:
            # A direction column beats any sign convention: the amount beside it
            # is a magnitude, so its own sign (usually absent) means nothing.
            magnitude = parse_signed_money(cell(record, profile.amount))
            if magnitude is None:
                amount = None
            elif any(word in kind_value for word in DEBIT_WORDS):
                amount = abs(magnitude)
            else:
                amount = -abs(magnitude)
        else:
            signed = parse_signed_money(cell(record, profile.amount))
            amount = None if signed is None else signed * profile.expense_sign

        if when is None or amount is None:
            out.append(
                ParsedRow(when, 0, description, "", "error",
                          "could not read the date or amount")
            )
            continue

        # An issuer category can name a row as a credit even where the sign does
        # not, as Discover does on its payment lines.
        if amount > 0 and issuer_category.strip().lower() in CREDIT_CATEGORIES:
            amount = -amount

        if amount == 0:
            out.append(ParsedRow(when, 0, description, "", "skipped", "zero amount"))
            continue

        # ---- money in ------------------------------------------------------
        if amount < 0:
            received = -amount
            if not capture_income:
                out.append(
                    ParsedRow(when, received, description, "", "skipped",
                              "credit, not imported", "income")
                )
                continue
            source = guess_income_source(description, fallback_income_source)
            key = (when.isoformat(), received, description.strip().lower())
            if key in income_fingerprints or key in seen_in:
                out.append(
                    ParsedRow(when, received, description, source, "duplicate",
                              "already in your income", "income")
                )
                continue
            seen_in.add(key)
            out.append(ParsedRow(when, received, description, source, "new", "", "income"))
            continue

        # ---- money out -----------------------------------------------------
        category = (
            map_category(issuer_category, fallback_category)
            if use_issuer_categories
            else fallback_category
        )
        key = (when.isoformat(), amount, description.strip().lower())
        if key in fingerprints or key in seen_out:
            out.append(
                ParsedRow(when, amount, description, category, "duplicate",
                          "already in your log")
            )
            continue
        seen_out.add(key)
        out.append(ParsedRow(when, amount, description, category, "new"))

    return out


def load(
    path: str | Path,
    profile: Profile | None = None,
    fallback_category: str = "Other",
    use_issuer_categories: bool = True,
    fingerprints: set[tuple[str, int, str]] | None = None,
    income_fingerprints: set[tuple[str, int, str]] | None = None,
    capture_income: bool = True,
) -> ImportResult:
    headers, records = read_table(path)
    profile = profile or detect(headers)
    rows = parse_rows(
        records,
        profile,
        fallback_category,
        use_issuer_categories,
        fingerprints,
        income_fingerprints,
        capture_income,
    )
    return ImportResult(headers=headers, profile=profile, rows=rows)


# ---------------------------------------------------------------------- writing

EXPORT_COLUMNS = ["Date", "Amount", "Category", "Description", "Notes", "Source"]


def export_expenses(rows, path: str | Path) -> int:
    """Write expense rows to CSV. Amounts are plain decimals, no currency symbol,
    so the file re-imports cleanly and spreadsheets treat the column as numeric."""
    written = 0
    # utf-8-sig keeps Excel happy with non-ASCII descriptions.
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(EXPORT_COLUMNS)
        for row in rows:
            source = row["subscription_name"] if row["subscription_id"] is not None else "Manual"
            writer.writerow(
                [
                    row["spent_on"],
                    f"{row['amount_cents'] / 100:.2f}",
                    row["category"],
                    row["description"],
                    row["notes"],
                    source or "Subscription",
                ]
            )
            written += 1
    return written
