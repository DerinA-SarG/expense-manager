# Expense Manager

A local, single-user desktop app for tracking expenses and subscriptions.
No server, no accounts, no network access — everything lives in one SQLite file
on your machine.

Built with **Python 3 + PySide6 (Qt 6)**, which is why it runs the same on
Windows 11 and on Linux (Ubuntu, Arch, anything with Qt 6).

## Getting started

**Easiest on Windows — download the app.** Grab `ExpenseManager.exe` from the
[Releases](../../releases) page and double-click it. No Python needed. It is
unsigned, so SmartScreen will warn you on first launch: "More info → Run anyway".

**From source, any OS.** Needs **Python 3.9 or newer**:

```bash
pip install -r requirements.txt
python main.py
```

On Windows you can double-click `run.bat` instead (it uses `pythonw`, so no
console window tags along). On Linux, `./run.sh`.

> **If you have more than one Python installed,** make sure PySide6 lands in the
> same interpreter you launch with. `pip install` and `python` can easily be
> different installs, and the symptom is `ModuleNotFoundError: No module named
> 'PySide6'` even though pip said it succeeded. Using
> `python -m pip install -r requirements.txt` avoids it, since that installs
> into whichever Python you just named. A virtual environment sidesteps the
> problem entirely:
>
> ```bash
> python -m venv .venv
> .venv\Scripts\activate      # Linux/macOS: source .venv/bin/activate
> python -m pip install -r requirements.txt
> python main.py
> ```

### Where your data lives

One SQLite file in the usual per-user spot for your OS — `%APPDATA%` on Windows,
`~/.local/share` on Linux, `~/Library/Application Support` on macOS. Nothing is
written into the project folder, and nothing is ever sent anywhere.

To look around before entering real data, open a throwaway database seeded with
four months of sample spending:

```bash
python main.py --demo
```

## The five pages

The sidebar carries a small tracker under the navigation — **Enter Income**,
**Enter Expenses**, **Update Goals** — which ticks off as you do each one and
starts empty again at every launch. It is asking what you have done since you
opened the window, so it deliberately remembers nothing between sittings. Click
a step to jump to the page it belongs to.

**Overview** — a donut chart of spending by category for a period you pick
(this month, last month, last 3 months, year to date, all time). Beside it is a
ranked list giving each category's exact amount, share, and a comparison bar;
hovering either the chart or the list highlights the same category in both.
Five stat cards across the top cover total spent, income, net, average per day,
and what your active subscriptions cost per month. Net is the one figure whose
sign changes its meaning, so it is the one that carries colour — green when you
kept money, red when you spent past what came in, with the caption saying which
either way.

**Expenses** — the full log. Search by description, note or category, filter by
category and period, and sort any column. Add with the button or `Ctrl+N`,
double-click a row to edit, select one or many and press `Delete` to remove
them. The footer totals whatever the current filters have selected. This page
also carries **Import CSV**, **Export CSV** and the **Categories** manager.

**Subscriptions** — recurring charges. Each one has an amount, a billing cycle
(weekly through yearly), a category and the date it was first billed on. That
date and the cycle are the whole schedule: charges post themselves to your
expense log one cycle at a time, and a subscription entered with a start date in
the past posts the charges it has already run up the moment you save it. The
page shows what each costs normalised per month, so a yearly domain renewal and
a monthly streaming plan are directly comparable, plus your total monthly and
yearly commitment.

**Income** — everything coming in, logged the same way expenses are: date,
amount, source, description. Sources work like categories — pick one or type a
new one. The page shows your total, your net against spending for the same
period, and which source is carrying the most. Deposits found in an imported CSV
land here automatically.

**Goals** — savings targets, each drawn as its own progress ring. A goal has a
name, a target, and **a share of your income**: put 10% on an emergency fund and
every pay packet you log works out what that goal is owed. You can still add
money by hand, and a goal set to 0% is entirely manual.

Nothing moves until you say so. Logging income leaves a share *waiting*; a
banner at the top of the page says exactly how much that comes to and which
goals it would go into, and **Update goals** is what actually sets it aside.
**Skip** takes that income out of the queue without saving any of it, for the
month the money was needed elsewhere.

- **A goal never holds more than its target.** Once it is full, the share it
  would have taken goes to the goals that still have room, split between them in
  proportion to the share of income each one takes. Money you hand to a full goal
  yourself flows on the same way, and the dialog says where it will land while
  you are still typing the amount. Where every goal is full, the remainder is not
  set aside at all and the page says so — it is never quietly dropped.
- A goal that is already over its target — topped up by hand, or had its target
  lowered afterwards — gets its own banner offering to share the excess out.
- **Reset progress** in the edit dialog empties a goal without deleting it: the
  goal, its target and its share all stay, and you choose whether the money is
  cleared or moved into your other goals. Nothing happens until you save.
- Each contribution remembers the percentage it was cut at. Changing a goal's
  percentage therefore applies from that point on and leaves money already set
  aside exactly as it is — a decision made today does not restate what you
  banked in March. Income still waiting is re-quoted at the new share.
- Delete an income entry and its share goes with it. Edit one that has already
  been applied and its share is re-cut at the percentage it was originally set
  aside at, because correcting a payslip is a correction to that payslip and
  nothing more. Edit one that is still waiting and it is simply re-quoted.
- Money you added by hand is never touched by any of that — it has no income
  behind it, so it survives every recalculation.
- Imported CSV income queues up exactly like income you typed in.
- The dialog tells you what a percentage works out to on a typical pay packet,
  and warns you if your goals between them would claim more than 100% of what
  comes in. Rings turn green at 100%, and taking money back out is stored as a
  negative contribution so the total stays a plain sum.

## Importing from your bank or card

**Expenses → Import CSV.** Download a transaction export from your issuer and
open it here. These layouts are recognised automatically:

| Issuer | Shape |
|--------|-------|
| **Discover** | one signed `Amount` column — purchases positive, payments negative |
| **Capital One** (credit) | separate `Debit` and `Credit` columns |
| **Capital One** (bank) | unsigned `Transaction Amount` plus a Debit/Credit column |
| Anything else | columns guessed by name, then mapped by hand |

Whatever is detected, the dialog shows you the column mapping and a full
preview before a single row is written, and every column picker is editable —
so a layout that changes, or one that was never recognised, is still importable.

- **Money out becomes an expense, money in becomes income.** Credits are not
  folded into the spending log as negatives — that would corrupt the chart — so
  each row is classified by direction and routed to the right page. Income
  sources are guessed from the description where the wording allows it
  (`...PAYROLL` → Salary, `Interest Paid` → Interest). Untick *Bring deposits in
  as income* to leave credits out entirely.
- **Duplicates are detected** on date, amount and description, separately for
  expenses and income. Statement exports routinely overlap, so re-importing last
  month's file next to this one adds nothing twice — the repeats appear as
  *Already logged*.
- **Issuer categories are translated** where there is an obvious match
  (`Supermarkets` → Groceries, `Gas/Automotive` → Transport); the rest come
  through as-is, or you can ignore them entirely and file everything under one
  category.
- Rows with an unreadable date or amount are flagged rather than guessed at.

**Export CSV** writes exactly what the current filters show, so you can export
one category or one month as easily as everything. Amounts are plain decimals
with no currency symbol, so spreadsheets treat the column as numeric — and the
file imports straight back into the app unchanged.

## Managing categories

**Expenses → Categories** lists every category with how many expenses and
subscriptions use it, and the total filed under it.

- **Rename** fixes a typo. Renaming onto a name that already exists **merges**
  the two — everything filed under either ends up in one place.
- **Merge into…** does the same thing explicitly, for when you decide two
  categories should always have been one.
- **Delete** is only offered for a category nothing is using; anything in use
  has to be merged instead, so entries can never be stranded.

## How subscriptions reach your expense log

A subscription is a rule, not a number that sits off to the side. When a charge
comes due, the app writes a real expense into the log — so the pie chart, the
totals and the log all reflect actual money spent, with no double counting.

- Charges post on launch, and whenever you add, edit, pause or resume one.
- Anything that came due while the app was closed is caught up at the next
  launch, and you get a note saying how many were added.
- Posting is idempotent. The next-due date is advanced past today and saved, so
  a charge is never posted twice no matter how often you open the app.
- Back-dating works: set the next-due date in the past and every charge from
  then to today is added at once. The dialog warns you before you save.
- Posted charges show the subscription's name in the log's **Source** column;
  everything you entered by hand reads *Manual*.
- Monthly cycles anchor to the original billing day, so a subscription billed on
  the 31st lands on Feb 28 and then goes back to Mar 31 rather than drifting
  earlier each month.
- Pausing stops future charges but keeps the history. Deleting a subscription
  also keeps its posted charges by default — they were real spending — though
  the confirmation dialog offers to remove them too.

## Deleting data

**Delete data…** at the bottom of the sidebar clears records out. It is
deliberately awkward, because there is no undo:

- Tick only what you want gone — expenses, income, subscriptions, goals, or
  custom categories — each shown with its exact record count. A bad import
  can be cleared without touching your goals.
- A timestamped backup of the database is taken first by default, and the
  dialog names the file afterwards. If the backup fails, nothing is deleted.
- You have to type `DELETE`. A checkbox is too easy to click through.
- Clearing subscriptions also removes the charges they posted, since those were
  the subscription's doing; expenses you typed in yourself are left alone.
- Clearing categories restores the built-in set rather than leaving you with an
  empty dropdown.

## Your data

One SQLite file, created on first run:

| OS | Location |
|----|----------|
| Windows | `%APPDATA%\ExpenseManager\expenses.db` |
| Linux | `~/.local/share/ExpenseManager/expenses.db` |
| macOS | `~/Library/Application Support/ExpenseManager/expenses.db` |

Hover *Saved on this PC* at the bottom of the sidebar to see the exact path.
Back it up by copying that file. Point the app at a different one with
`python main.py --db path/to/other.db`.

Amounts are stored as integer cents, never floats, so repeated sums cannot drift
by a penny.

## Settings

Everything that is not navigation sits behind the **gear at the bottom of the
sidebar**, so the sidebar reads as a list of places rather than a control panel:

- **Currency** — pick a symbol, or type your own under *Something else…*
- **Dark mode** — a checkable toggle
- **Back up now…** — writes a timestamped copy of the database and tells you where
- **Show data folder** — opens the folder your database lives in
- **Delete data…** — the selective wipe described above

The currency and theme both persist between sessions.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+N` | Add expense |
| `Ctrl+Shift+N` | Add subscription |
| `Delete` | Delete selected expenses |
| Double-click | Edit the row |

## Building a standalone executable

```bash
pip install pyinstaller
python tools/build_exe.py
```

You get `dist/ExpenseManager.exe` (or `dist/ExpenseManager` on Linux) with
Python and Qt bundled in, so it runs on machines with no Python installed. Your
database stays in the per-user data directory, so replacing the binary never
disturbs it.

## Linux notes

Qt 6 needs a handful of X11/Wayland libraries that desktop installs normally
already have. If the app fails to start with an `xcb` plugin error:

```bash
# Debian / Ubuntu
sudo apt install libxcb-cursor0 libxkbcommon-x11-0

# Arch
sudo pacman -S libxcb xcb-util-cursor libxkbcommon-x11
```

## Project layout

```
main.py                  entry point and CLI flags
expman/
  db.py                  SQLite schema and all queries
  money.py               parsing and formatting of integer-cent amounts
  allocation.py          who gets what: capped splits and overflow, no writes
  journey.py             the three-step tracker in the sidebar
  recurrence.py          billing-cycle maths (month clamping, normalisation)
  csvio.py               issuer CSV profiles, parsing, duplicate keys, export
  theme.py               light/dark palettes, stylesheet, generated icons
  charts.py              donut, ranked legend and goal rings, custom-painted
  ledger.py              table model + view for the expense and income logs
  widgets.py             cards, stat tiles, headers, empty states, table helpers
  dialogs.py             add/edit forms, income, goals, category manager,
                         delete-data
  import_dialog.py       CSV mapping and preview
  app.py                 main window and sidebar navigation
  pages/
    overview.py          chart page
    expenses.py          log page, CSV entry points
    subscriptions.py     recurring charges page
    income.py            money-in page
    goals.py             savings targets, fed by a share of income
tools/
  seed_demo.py           generates the sample database
  smoke_ui.py            drives the core UI handlers with stubbed dialogs
  smoke_features.py      goals, allocation, income, categories, CSV round-trip
  diagnose_freeze.py     runs the app with a UI-stall watchdog
  render_check.py        renders every page to PNG, headless
  render_dialogs.py      renders dialogs and empty states
  build_exe.py           PyInstaller bundling
```

## Checks

```bash
python tools/smoke_ui.py        # 64 assertions
python tools/smoke_features.py  # 228 assertions
```

The first covers add / edit / delete for expenses and subscriptions,
subscription posting and idempotency, orphaning rules, filters, search, period
ranges, theme and currency persistence, and navigation.

The second covers CSV detection and parsing for all three issuer layouts, the
expense/income split, duplicate detection on both sides, export round-tripping,
category rename / merge / delete, income entry and net calculation, goal
contributions, withdrawals, completion and cascade deletion, the income-to-goal
rules (nothing moves until it is applied, idempotency, rate-stability, manual
money surviving a recut), the overflow rules (a full goal takes only what fits,
the rest reaches the goals with room, money with nowhere to go is reported
rather than lost), resetting a goal, sharing out what is over target, the
sidebar tracker, and the delete-data flow including selective wipes, backups and
the typed confirmation. Neither needs a display.

```bash
python tools/render_check.py shots/
```

Writes a PNG of every page in both themes, so layout changes can be eyeballed
without launching anything.

## Design notes

Category colours come from a fixed eight-hue order chosen for colour-vision
separation on adjacent pairs, with light and dark variants stepped separately
against their own surface rather than one being an inversion of the other. Past
eight categories the tail folds into a single neutral *Other* slice instead of
inventing a ninth hue. Because the ranked list names, values and bar-scales
every category, nothing in the chart depends on colour alone — and the same rule
governs the goal rings, where a ring turning green is always accompanied by the
words "Target reached".

The two logs that grow without limit — expenses and income — are a
`QTableView` over a `LedgerModel` rather than a `QTableWidget`. A widget-based
table allocates one item object per cell every time it is refilled, so the cost
of opening a page scaled with the size of the log; the model formats cells on
demand and only for rows actually on screen, which keeps a refresh flat from a
hundred rows to ten thousand. Column widths sample the first few dozen rows
rather than measuring every one.

The smaller, bounded tables still use `QTableWidget`, refilled through a
`filling()` helper that suspends repaints, sorting and signals. Blocking
signals matters beyond speed: without it, inserting rows churns the selection
and the selection handlers read back into the model while it is still being
mutated.

Refreshes are scoped to the visible page. Every page reads the same database,
so an edit invalidates all six, but the five nobody is looking at are refreshed
when they are next opened instead. Search boxes are debounced, so typing costs
one query rather than one per keystroke. Modal dialogs opened from a widget's
own double-click handler are deferred by an event-loop turn, so a refresh can
never destroy the widget whose handler is still unwinding.

Splitting money between goals lives in one module, `allocation.py`, which
returns plans and writes nothing. The page shows the plan and the database walks
the same split to apply it, so what a button says it will do and what it does
cannot drift apart. Every split hands out whole cents by largest remainder and
adds up to exactly what went into it: what cannot be placed comes back as a
figure the caller has to say something about, because the alternative is a
rounding rule that loses somebody's money.

Money is integer cents from the database up to the formatting layer, and the
same decimal parser serves both the amount field and the CSV importer, so
`1,234.56` and `1.234,50` are read identically wherever they appear. The figure
in the middle of a donut is shown in full and shrunk to fit rather than
abbreviated, so it can never disagree with the total printed beside it.

## Licence

MIT — see [LICENSE](LICENSE).
