"""Expense Manager -- launch script.

    python main.py                     use the standard per-user data location
    python main.py --db path/to.db     use a specific database file
    python main.py --demo              open a throwaway database with sample data
"""
from __future__ import annotations

import argparse
import sys

from expman.app import run


def main() -> int:
    parser = argparse.ArgumentParser(description="Local expense manager.")
    parser.add_argument("--db", metavar="PATH", help="database file to open")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="open a temporary database seeded with sample data",
    )
    args = parser.parse_args()

    db_path = args.db
    if args.demo:
        from tools.seed_demo import build_demo_db

        db_path = build_demo_db()
        print(f"Demo database: {db_path}")

    return run(db_path)


if __name__ == "__main__":
    sys.exit(main())
