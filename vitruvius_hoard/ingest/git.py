"""Shallow git clone / fetch into ``data/sources/<id>``. Requires the ``git`` binary."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


def git_available() -> bool:
    return shutil.which("git") is not None


def clone_or_pull(url: str, dest: Path, *, timeout: float = 120.0) -> tuple[bool, str, Optional[str]]:
    """Returns (ok, message, commit_sha)."""
    if not git_available():
        return False, "git is not installed on this machine", None
    dest = Path(dest)
    try:
        if (dest / ".git").is_dir():
            result = subprocess.run(
                ["git", "-C", str(dest), "pull", "--ff-only"],
                capture_output=True, text=True, timeout=timeout,
            )
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            result = subprocess.run(
                ["git", "clone", "--depth", "1", url, str(dest)],
                capture_output=True, text=True, timeout=timeout,
            )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "git failed").strip()[:2000], None
        commit = current_commit(dest)
        return True, "ok", commit
    except subprocess.TimeoutExpired:
        return False, f"git timed out after {timeout}s", None
    except OSError as error:
        return False, str(error), None


def current_commit(dest: Path) -> Optional[str]:
    try:
        result = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        pass
    return None
