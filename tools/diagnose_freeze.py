"""Run the app with a watchdog that records what it is doing while frozen.

    python tools/diagnose_freeze.py

Use the app normally and reproduce the freeze once. Two things get recorded to
freeze-report.txt next to this project:

* an event-loop heartbeat, which measures how long the UI was actually wedged;
* a stack dump of the main thread taken every few seconds from a separate
  thread, so it still fires while the main thread is blocked.

If the stack dumps land inside Qt code the problem is ours; if the main thread
looks idle in the event loop the whole time, the block is below Python -- a
driver, security software, or the window manager -- and the heartbeat timings
will say so. Close the app when you are done.
"""
from __future__ import annotations

import faulthandler
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from expman.app import APP_NAME, MainWindow, make_icon  # noqa: E402
from expman.db import Database  # noqa: E402

REPORT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "freeze-report.txt"
)

# How long the loop may be blocked before it counts as a stall worth recording.
STALL_MS = 1500
HEARTBEAT_MS = 250
DUMP_EVERY_S = 3


class Heartbeat:
    """Times the gaps between timer ticks; a long gap is a frozen UI."""

    def __init__(self, log):
        self.log = log
        self.last = time.perf_counter()
        self.worst = 0.0
        self.stalls = 0

    def tick(self) -> None:
        now = time.perf_counter()
        gap_ms = (now - self.last) * 1000
        self.last = now
        if gap_ms > STALL_MS:
            self.stalls += 1
            self.worst = max(self.worst, gap_ms)
            stamp = time.strftime("%H:%M:%S")
            line = f"[{stamp}] UI STALLED for {gap_ms / 1000:.1f} s"
            print(line, flush=True)
            self.log.write(line + "\n")
            self.log.flush()


def main() -> int:
    log = open(REPORT, "w", encoding="utf-8", buffering=1)
    log.write(f"Expense Manager freeze report - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    log.write(f"Python {sys.version.split()[0]} on {sys.platform}\n")
    try:
        import PySide6

        log.write(f"PySide6 {PySide6.__version__}\n")
    except Exception:
        pass
    log.write("=" * 70 + "\n\n")

    # Dumps the MAIN thread's stack from a watchdog thread, so it still reports
    # while the main thread is wedged.
    faulthandler.enable(file=log)
    faulthandler.dump_traceback_later(DUMP_EVERY_S, repeat=True, exit=False, file=log)

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "zephr.expensemanager.diagnose"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)

    db = Database()
    window = MainWindow(db)
    window.setWindowTitle(APP_NAME + "  [diagnostic mode]")
    window.show()
    app.setWindowIcon(make_icon(window.pal["accent"], window.pal["surface"]))

    beat = Heartbeat(log)
    timer = QTimer()
    timer.timeout.connect(beat.tick)
    timer.start(HEARTBEAT_MS)

    print("=" * 66)
    print("Diagnostic mode. Reproduce the freeze once, then close the window.")
    print("  1. Expenses -> Import CSV...")
    print("  2. Choose file, pick your Capital One export")
    print("  3. Click one of the dropdowns and wait for it to unfreeze")
    print(f"\nRecording to: {REPORT}")
    print("=" * 66, flush=True)

    code = app.exec()

    faulthandler.cancel_dump_traceback_later()
    summary = (
        f"\nSummary: {beat.stalls} stall(s) over {STALL_MS} ms; "
        f"worst {beat.worst / 1000:.1f} s\n"
    )
    print(summary, flush=True)
    log.write("=" * 70 + summary)
    log.close()
    print(f"Report written to {REPORT}")
    return code


if __name__ == "__main__":
    sys.exit(main())
