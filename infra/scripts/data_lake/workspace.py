"""Locate the Book Dev checkout folder that holds the product repositories.

This repository is self-contained: its contracts, schemas, and fixtures live
here, and its own repository root is the lake runtime root. The Book Dev
*product* repositories (``book-news-scraping``, ``book-job-data``,
``book-crypto-data``, ...) are separate repositories that the capture/ingest
runners read from. They are found under ``$SOLO_BOOK_DEV_ROOT``: the folder
that contains ``github/`` (for example ``<hub>/projects/product/engineering/book-dev``).
When it is unset or absent the runners report their sources as missing, and
tests that need a product repository skip.
"""

from __future__ import annotations

import os
from pathlib import Path

OWNER_REL = "github/bookchaowalit"
# Registry/contract paths are written with this historical hub prefix; it is
# stripped so they resolve under ``$SOLO_BOOK_DEV_ROOT``.
_LEGACY_PREFIX = "projects/product/engineering/book-dev/"
_UNSET = Path("/nonexistent/SOLO_BOOK_DEV_ROOT-not-set")


def book_dev_root() -> Path:
    configured = (os.environ.get("SOLO_BOOK_DEV_ROOT") or "").strip()
    return Path(configured).expanduser() if configured else _UNSET


WORKSPACE = book_dev_root()
OWNER_ROOT = WORKSPACE / OWNER_REL


def product_path(relative: str) -> Path:
    """Resolve a registry path (``.../book-dev/github/...``) under the Book Dev root."""
    if relative.startswith(_LEGACY_PREFIX):
        relative = relative[len(_LEGACY_PREFIX):]
    return WORKSPACE / relative


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
    """True when ``relative`` (a path under the Book Dev root) exists."""
    return product_path(relative).exists()
