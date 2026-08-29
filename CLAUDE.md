# CLAUDE.md — Expense Manager

Instructions for Claude working in this repo. Read before changing anything.

## What this is

A local, single-user desktop app for tracking expenses, subscriptions, income
and savings goals. Python 3.9+ with PySide6 (Qt 6), storing everything in one
SQLite file. No server, no accounts, no network calls anywhere in the app.

## Ground rules

1. **Money is integer cents, everywhere below the UI.** `expman/money.py` is
   the only place that converts. Floats are produced for display and never
   stored, summed or compared. A float creeping into the data layer is a bug
   even when the test still passes.
2. **No network access except the update check, and only when asked.** This
   app handles someone's financial records: no telemetry, no cloud sync,
   nothing that reaches anywhere on a timer, and it must stay that way. The one
   exception is `expman/updates.py`, which shells out to `git fetch` when
   someone presses "Check for updates" in the settings menu. Git is how the
   project is distributed, so the check reuses it rather than putting an HTTP
   client inside a finance app -- and a fetch asks for commits without offering
   anything about the machine asking. Adding an HTTP client is still a design
   change, not an implementation detail.
3. **The database never lives in the project folder.** `default_data_dir()`
   resolves `%APPDATA%` / `~/.local/share` / `~/Library/Application Support`.
   `*.db` is gitignored so spending data can never be committed — keep it that
   way.
4. **Historical figures are not restated.** Goal contributions remember the
   percentage they were cut at. Changing a goal's percentage applies from that
   point forward and leaves money already set aside untouched. Editing an
   income entry re-cuts its share at the rate it was *originally* set aside at.
   This is deliberate: a correction to one payslip must not silently rewrite
   what was banked in March.
5. **Money in and money out are different things.** Credits are never folded
   into the expense log as negative expenses — that would corrupt the category
   chart. CSV rows are classified by direction and routed to expenses or
   income accordingly.
6. **`SCHEMA_VERSION` in `expman/db.py` must be bumped** when the schema
   changes, and existing databases must keep opening.

## Repo map

```
main.py                 entry point; --db PATH and --demo flags
expman/
  app.py                MainWindow, navigation, theme plumbing
  db.py                 schema + every query (largest module, start here)
  money.py              cents parsing/formatting, locale-aware decimals
  ledger.py             shared query/aggregation helpers
  recurrence.py         subscription billing-cycle arithmetic
  csvio.py              issuer detection, CSV parse and export
  updates.py            git comparison behind "Check for updates"
  import_dialog.py      the import wizard
  dialogs.py            add/edit dialogs, category manager, wipe
  charts.py             donut and progress-ring painting
  theme.py              palette and styling
  widgets.py            shared custom widgets
  pages/                overview, expenses, subscriptions, income, goals
tools/                  test and build scripts (see below)
```

Tables: `meta`, `categories`, `subscriptions`, `expenses`, `income_sources`,
`income`, `goals`, `goal_contributions`.

## Commands

```bash
python -m pip install -r requirements.txt
python main.py                 # normal launch
python main.py --demo          # throwaway db with four months of sample data
python main.py --db test.db    # point at a specific file
```

Use `python -m pip`, not bare `pip`. Multiple interpreters on PATH is the
normal case and PySide6 landing in the wrong one is the most common setup
failure by a wide margin.

## How to verify a change

There are two smoke suites. **Run both before claiming a change works.** They
drive the real widgets with dialogs stubbed, so handlers are exercised rather
than just the data layer underneath.

```bash
QT_QPA_PLATFORM=offscreen python tools/smoke_features.py   # 113 checks
QT_QPA_PLATFORM=offscreen python tools/smoke_ui.py         # 30 checks
```

`smoke_features.py` covers goals, income, the category manager and CSV
import/export. `smoke_ui.py` covers add/edit/delete, subscription posting,
filters, theme and currency changes. Both print `N passed, M failed` and exit
non-zero on failure. Add checks there when you add behaviour — the existing
style is one `check(label, condition, detail)` per assertion, grouped under a
printed heading.

For anything visual:

```bash
python tools/render_check.py OUT_DIR      # every page to PNG, offscreen
python tools/render_dialogs.py OUT_DIR    # dialogs and first-run empty states
```

Then actually look at the PNGs. If the app hangs, `tools/diagnose_freeze.py`
runs it under a watchdog and writes `freeze-report.txt`.

## Conventions

- `from __future__ import annotations` at the top of every module; that is what
  keeps the 3.9 floor while allowing `X | None` annotations.
- Four-space indent, type hints on public functions.
- Qt widgets are built in a `_build()` method; signals connected in one place.
- Pages rebuild lazily — a hidden page has not rebuilt yet and picks changes up
  when opened. Do not force eager rebuilds; the smoke suite asserts this.
- Comments explain *why*. `money.py` and the goals logic carry the density,
  because their rules are non-obvious and easy to "fix" wrongly.
- British spelling in UI text and comments.

## Things that will bite you

- **PySide6 in the wrong interpreter.** Symptom is `ModuleNotFoundError: No
  module named 'PySide6'` after pip reported success. Use `python -m pip`, or a
  venv.
- **Qt needs a display.** Any headless run needs `QT_QPA_PLATFORM=offscreen`.
- **`run.bat` uses `pythonw`** so no console window appears. If the app dies
  silently on Windows, rerun with `python main.py` to see the traceback.
- **`.sh` files need LF endings.** `.gitattributes` enforces it.

## Building the executable

```bash
python -m pip install pyinstaller
python tools/build_exe.py      # -> dist/ExpenseManager.exe
```

Unsigned, so SmartScreen warns on first launch for anyone who downloads it.
Ship it via GitHub Releases, never committed — `dist/` is gitignored and a
binary in git history is permanent.

## If you are rebuilding this from scratch

The order that works: schema and `money.py` first, with the cents discipline
established before any UI exists. Then the data layer with its queries. Then
pages one at a time, each with smoke checks written alongside it rather than
afterwards. CSV import last — it is the largest surface area and the easiest to
get subtly wrong, and it depends on everything else already being trustworthy.

Write the check before the feature where you can. The 113 assertions in
`smoke_features.py` are what make this codebase safe to change.
