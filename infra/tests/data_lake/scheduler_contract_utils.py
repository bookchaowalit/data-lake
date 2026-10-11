"""Shared shell resolution for offline scheduler contract tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path


def _candidates() -> list[str]:
    candidates: list[str] = []
    if os.name == "nt":
        roots: list[str] = []
        for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            root = os.environ.get(variable)
            if root and root not in roots:
                roots.append(root)
        for root in (r"C:\Program Files", r"C:\Program Files (x86)"):
            if root not in roots:
                roots.append(root)
        for root in roots:
            candidates.extend(
                [
                    str(Path(root) / "Git" / "bin" / "bash.exe"),
                    str(Path(root) / "Git" / "usr" / "bin" / "bash.exe"),
                ]
            )
        located = shutil.which("bash")
        if located and "git" in located.casefold():
            candidates.append(located)
    else:
        located = shutil.which("bash")
        if located:
            candidates.append(located)
    return candidates


def _usable(path: str) -> bool:
    try:
        completed = subprocess.run(
            [path, "-c", "exit 0"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def require_bash() -> str:
    """Return a usable Git Bash path or skip the current test clearly."""
    seen: set[str] = set()
    for candidate in _candidates():
        normalized = os.path.normcase(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            if Path(candidate).is_file() and _usable(candidate):
                return candidate
        except OSError:
            continue
    raise unittest.SkipTest(
        "No usable Git Bash executable found; scheduler shell contract test skipped"
    )
