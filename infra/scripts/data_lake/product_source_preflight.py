#!/usr/bin/env python3
"""Report whether separate source-product repos are available for CI evidence.

This check is intentionally local and read-only. It does not clone repositories,
call GitHub, read credentials, or inspect remote URLs. A later checkout step may
populate the same paths; this script then verifies the package boundaries before
the product parity runner is allowed to execute.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

# Product repositories live under the Book Dev root ($SOLO_BOOK_DEV_ROOT, the
# folder that contains github/), not in this repository.
ROOT = Path(os.environ.get("SOLO_BOOK_DEV_ROOT") or "/nonexistent/SOLO_BOOK_DEV_ROOT-not-set").expanduser()

PRODUCTS = (
    {
        "name": "book-crypto-data",
        "package": "book_crypto",
        "relative_path": "github/bookchaowalit/public/book-products/book-crypto-data",
    },
    {
        "name": "book-stock-data",
        "package": "book_stock",
        "relative_path": "github/bookchaowalit/public/book-products/book-stock-data",
    },
    {
        "name": "book-fx-data",
        "package": "book_fx",
        "relative_path": "github/bookchaowalit/public/book-products/book-fx-data",
    },
)


def _git_probe(path: Path, *args: str) -> bool:
    if not (path / ".git").exists():
        return False
    result = subprocess.run(
        ["git", "-C", str(path), *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def build_report(root: Path = ROOT) -> dict[str, Any]:
    """Return a redacted source-readiness report for the configured root."""
    products: list[dict[str, Any]] = []
    for product in PRODUCTS:
        product_path = root / product["relative_path"]
        package_path = product_path / "src" / product["package"]
        source_available = package_path.is_dir()
        products.append(
            {
                "product": product["name"],
                "package": product["package"],
                "path": product["relative_path"],
                "source_available": source_available,
                "git_metadata_present": (product_path / ".git").exists(),
                "git_head_present": _git_probe(product_path, "rev-parse", "--verify", "HEAD"),
                "origin_configured": _git_probe(product_path, "config", "--get", "remote.origin.url"),
            }
        )

    available_count = sum(1 for item in products if item["source_available"])
    if available_count == len(products):
        status = "available"
    elif available_count:
        status = "partial"
    else:
        status = "unavailable"
    return {
        "status": status,
        "available_count": available_count,
        "expected_count": len(products),
        "network": "not-used",
        "credentials": "not-read",
        "products": products,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root to inspect")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    parser.add_argument(
        "--require-available",
        action="store_true",
        help="Return exit code 2 unless all configured product sources are present",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = build_report(args.root.resolve())
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    if args.require_available and report["status"] != "available":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
