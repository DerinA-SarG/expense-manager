"""Comparing this build against the checkout it came from.

The app makes no network calls of its own: no telemetry, no sync, nothing on a
timer. This module is the single exception, and even here nothing happens until
someone presses "Check for updates". It shells out to git -- which is how the
project is distributed in the first place -- rather than teaching an app that
holds someone's financial records to speak HTTP. Nothing is sent: a fetch asks
for commits and offers nothing about the machine asking.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Long enough for a slow network, short enough that a wedged git is not a hang.
TIMEOUT = 25

# A --windowed build has no console, so every git call would otherwise flash one
# up. The flag does not exist off Windows, where there is nothing to suppress.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class GitUnavailable(RuntimeError):
    """No git, no checkout, or no answer from the network."""


@dataclass(frozen=True)
class Update:
    """What one comparison found."""

    branch: str
    behind: int
    ahead: int
    dirty: bool
    subjects: tuple[str, ...]

    @property
    def available(self) -> bool:
        return self.behind > 0


def is_frozen() -> bool:
    """True in the packaged executable, where the code is a frozen copy."""
    return bool(getattr(sys, "frozen", False))


def repo_root(start: Path | None = None) -> Path | None:
    """The checkout this build came from, if it is still sitting in one.

    The packaged executable lives in dist/ inside the checkout, so the walk
    starts from the executable; a source run starts from this file. A copy of
    the .exe taken somewhere else finds nothing, which is the honest answer --
    there is no checkout to compare it against.
    """
    if start is None:
        start = Path(sys.executable if is_frozen() else __file__)
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _git(root: Path, *args: str, timeout: int = TIMEOUT) -> str:
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise GitUnavailable("Git is not installed, or is not on the PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitUnavailable(
            "Git did not answer in time. Is the network up?"
        ) from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip()
        raise GitUnavailable(detail or f"git {args[0]} failed.")
    return done.stdout.strip()


def check(root: Path | None = None) -> Update:
    """Fetch and compare, without changing anything in the checkout.

    A fetch writes only to git's own record of what the remote holds; the files
    on disk, and the branch, are left exactly where they were. Nothing is
    updated until pull() is called.
    """
    root = root or repo_root()
    if root is None:
        raise GitUnavailable(
            "This copy is not running from a git checkout, so there is nothing "
            "to compare it against."
        )

    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        raise GitUnavailable(
            "This checkout is not on a branch, so there is no remote to compare with."
        )

    _git(root, "fetch", "--quiet", "origin", branch)
    ahead, behind = (
        int(n)
        for n in _git(root, "rev-list", "--left-right", "--count", "HEAD...FETCH_HEAD").split()
    )
    subjects: tuple[str, ...] = ()
    if behind:
        log = _git(root, "log", "--format=%s", "HEAD..FETCH_HEAD")
        subjects = tuple(line for line in log.splitlines() if line.strip())
    return Update(
        branch=branch,
        behind=behind,
        ahead=ahead,
        dirty=bool(_git(root, "status", "--porcelain")),
        subjects=subjects,
    )


def pull(root: Path | None = None) -> str:
    """Fast-forward onto what the last check fetched. Returns git's own words.

    Fast-forward only, and against FETCH_HEAD rather than the network: the user
    agreed to the commits they were just shown, not to whatever has landed
    since, and not to a merge that rewrites local work. Anything else refuses
    and says why.
    """
    root = root or repo_root()
    if root is None:
        raise GitUnavailable("There is no checkout here to update.")
    return _git(root, "merge", "--ff-only", "FETCH_HEAD")
