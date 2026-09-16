"""Build a throwaway database with plausible sample data.

Used by ``python main.py --demo`` and by the render check in tools/render_check.py.
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from expman.db import Database  # noqa: E402

# category -> (weight, typical amount range in cents, sample descriptions)
PATTERN = {
    "Groceries": (26, (2200, 9800), ["Supermarket run", "Corner shop", "Butcher", "Market"]),
    "Dining": (18, (1100, 6400), ["Lunch out", "Coffee", "Takeaway", "Dinner with friends"]),
    "Transport": (14, (280, 4800), ["Bus pass", "Fuel", "Taxi", "Train ticket"]),
    "Shopping": (9, (1500, 12000), ["Clothes", "Household bits", "Books", "Gift"]),
    "Utilities": (6, (4200, 13500), ["Electricity", "Water", "Internet", "Phone bill"]),
    "Health": (5, (900, 8500), ["Pharmacy", "Dentist", "Gym drop-in"]),
    "Entertainment": (7, (1200, 7200), ["Cinema", "Concert", "Game", "Museum"]),
    "Other": (4, (500, 5000), ["Misc", "Postage", "Repairs"]),
}

SUBSCRIPTIONS = [
    ("Netflix", 1599, "Subscriptions", "monthly", 14),
    ("Spotify", 1099, "Subscriptions", "monthly", 3),
    ("iCloud storage", 299, "Subscriptions", "monthly", 21),
    ("Gym membership", 3500, "Health", "monthly", 1),
    ("Domain renewal", 1400, "Subscriptions", "yearly", 9),
    ("Car insurance", 42000, "Transport", "semiannual", 17),
]


def build_demo_db(path: str | None = None, seed: int = 7) -> str:
    rng = random.Random(seed)
    path = path or os.path.join(tempfile.mkdtemp(prefix="expman_demo_"), "demo.db")
    db = Database(path)
    db.set_setting("theme", "dark")

    today = date.today()
    start = today - timedelta(days=125)

    names = list(PATTERN)
    weights = [PATTERN[n][0] for n in names]

    # Rent posts on the first of each month.
    cursor = start.replace(day=1)
    while cursor <= today:
        if cursor >= start:
            db.add_expense(cursor, 132000, "Rent & Housing", "Monthly rent", commit=False)
        month = cursor.month + 1
        year = cursor.year + (month > 12)
        cursor = cursor.replace(year=year, month=month if month <= 12 else 1, day=1)

    day = start
    while day <= today:
        for _ in range(rng.choices([0, 1, 2, 3], weights=[18, 38, 30, 14])[0]):
            category = rng.choices(names, weights=weights)[0]
            _, (lo, hi), descriptions = PATTERN[category]
            db.add_expense(
                day,
                rng.randint(lo, hi),
                category,
                rng.choice(descriptions),
                commit=False,
            )
        day += timedelta(days=1)
    db.conn.commit()

    for name, cents, category, cycle, day_of_month in SUBSCRIPTIONS:
        first = (start + timedelta(days=2)).replace(day=day_of_month)
        db.add_subscription(name, cents, category, cycle, first, first)

    # Goals come first so that the income below is split across them the way
    # the app really does it, rather than being back-filled afterwards.
    for name, target, pct in (
        ("Emergency fund", 600000, 10.0),
        ("New laptop", 180000, 5.0),
        ("Winter trip", 90000, 0.0),
    ):
        db.add_goal(name, target, allocation_pct=pct)

    # Fortnightly pay plus the odd extra, so the Income page and the net figure
    # have something realistic to show.
    payday = start
    while payday <= today:
        db.add_income(payday, rng.randint(178000, 194000), "Salary",
                      "Fortnightly pay", commit=False)
        payday += timedelta(days=14)
    for _ in range(4):
        day = start + timedelta(days=rng.randint(0, (today - start).days))
        source, hi = rng.choice([("Freelance", 45000), ("Refund", 9000), ("Gift", 20000)])
        db.add_income(day, rng.randint(2500, hi), source, f"{source} payment", commit=False)
    db.add_income(today - timedelta(days=3), 412, "Interest", "Interest paid", commit=False)
    db.conn.commit()

    # Income does not move a goal on its own, so the demo stands in for someone
    # who has kept up: everything logged so far has been set aside...
    db.apply_pending()
    # ...and then one more pay packet arrives, which is what puts the "ready to
    # set aside" banner on the goals page with something real behind it.
    db.add_income(today - timedelta(days=1), 186000, "Salary", "Fortnightly pay")

    # One goal takes no share of income, so it needs topping up by hand.
    winter = next(g for g in db.goals() if g["name"] == "Winter trip")
    db.add_contribution(winter["id"], today - timedelta(days=20), 62000, "Sold the old bike")
    db.add_contribution(winter["id"], today - timedelta(days=4), 28000, "Birthday money")

    posted = db.post_due_subscriptions(today)
    print(f"seeded {len(db.list_expenses())} expenses ({posted} from subscriptions), "
          f"{len(db.goals())} goals")
    db.close()
    return path


if __name__ == "__main__":
    print(build_demo_db(sys.argv[1] if len(sys.argv) > 1 else None))
