"""Bundle the app into a single executable with PyInstaller.

    pip install pyinstaller
    python tools/build_exe.py

Produces dist/ExpenseManager.exe on Windows, dist/ExpenseManager on Linux.
The bundle is self-contained -- Python and Qt travel with it -- but the database
still lives in the per-user data directory, so upgrading the binary never
touches your data.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    if shutil.which("pyinstaller") is None:
        print("pyinstaller not found. Install it with:\n\n    pip install pyinstaller\n")
        return 1

    command = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--windowed",             # no console window
        "--onefile",
        "--name", "ExpenseManager",
        # Qt modules the app never touches; dropping them roughly halves the bundle.
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.QtMultimedia",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
        "--icon", os.path.join(ROOT, "assets", "expense-manager.ico"),
        os.path.join(ROOT, "main.py"),
    ]

    print(" ".join(command))
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode == 0:
        target = "ExpenseManager.exe" if sys.platform == "win32" else "ExpenseManager"
        print(f"\nBuilt: {os.path.join(ROOT, 'dist', target)}")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
