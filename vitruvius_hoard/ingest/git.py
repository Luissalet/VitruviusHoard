"""Shallow git clone / fetch into ``data/sources/<id>``. Requires the ``git`` binary."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from ..hoard_link import proc


def _env() -> dict[str, str]:
    """git must never wait for a password on a terminal that is not there: it fails at once instead."""
    return proc.build_env(GIT_TERMINAL_PROMPT="0")


def git_available() -> bool:
    return proc.which("git") is not None


def clone_or_pull(url: str, dest: Path, *, timeout: float = 120.0) -> tuple[bool, str, Optional[str]]:
    """Returns (ok, message, commit_sha)."""
    if not git_available():
        return False, "git is not installed on this machine", None
    dest = Path(dest)
    try:
        if (dest / ".git").is_dir():
            result = proc.run(["git", "-C", dest, "pull", "--ff-only"], timeout=timeout, env=_env())
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            result = proc.run(["git", "clone", "--depth", "1", url, dest], timeout=timeout, env=_env())
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
        result = proc.run(["git", "-C", dest, "rev-parse", "HEAD"], timeout=15, env=_env())
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None
