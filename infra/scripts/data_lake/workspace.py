"""Locate the Solo Empire workspace that holds the product repositories.

This repository is self-contained: its contracts, schemas, and fixtures live
here. The Book Dev *product* repositories (``book-news-scraping``,
``book-job-data``, ``book-crypto-data``, ...) are separate repositories that
the capture/ingest runners read from. They are found under
``$SOLO_EMPIRE_ROOT`` (default ``~/solo-empire``). When that tree is absent the
runners report their sources as missing, and tests that need a product
repository skip.
"""

from __future__ import annotations

import os
from pathlib import Path

OWNER_REL = "projects/product/engineering/book-dev/github/bookchaowalit"


def workspace_root() -> Path:
    configured = (os.environ.get("SOLO_EMPIRE_ROOT") or "").strip()
    return Path(configured).expanduser() if configured else Path.home() / "solo-empire"


WORKSPACE = workspace_root()
OWNER_ROOT = WORKSPACE / OWNER_REL


def relative_display(path: Path, repo_root: Path) -> str:
    """Stable redacted path for reports: workspace-relative, else repo-relative."""
    resolved = path if path.is_absolute() else repo_root / path
    for base in (WORKSPACE, repo_root):
        try:
            return str(resolved.relative_to(base))
        except ValueError:
            continue
    return resolved.name


def product_repo_available(relative: str) -> bool:
    """True when ``relative`` (a path under the workspace root) exists."""
    return (WORKSPACE / relative).exists()
