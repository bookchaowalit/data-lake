"""Offline tests for the technology-discovery capture replay contract."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "infra/scripts/data_lake/ingest_discovery_captures.py"
sys.path.insert(0, str(ROOT / "infra/scripts"))

from data_lake.ingest_discovery_captures import (  # noqa: E402
    CAPTURES,
    SOURCE_ROOT,
    _capture_lookup,
    map_records,
    normalize_timestamp,
)


class DiscoveryCaptureTests(unittest.TestCase):
    def test_timestamp_variants_are_normalized_to_utc(self) -> None:
        self.assertEqual(normalize_timestamp("2026-09-08 02:15:05"), "2026-09-08T02:15:05Z")
        self.assertEqual(normalize_timestamp("2026-09-08T02:15:05"), "2026-09-08T02:15:05Z")
        self.assertEqual(normalize_timestamp("2026-09-08T02:15:05+07:00"), "2026-09-07T19:15:05Z")
        self.assertEqual(normalize_timestamp("not-a-date"), "")

    def test_snapshot_capture_time_comes_from_history_when_source_omits_it(self) -> None:
        spec = next(item for item in CAPTURES if item.filename == "hackernews_top.csv")
        mapped = map_records(
            spec,
            [{"id": "123", "title": "Story", "url": "https://example.test/story", "time": "2026-09-08T01:00:00"}],
            capture_lookup={("hackernews", "123"): "2026-09-08T02:15:00Z"},
        )
        self.assertEqual(mapped[0]["captured_at"], "2026-09-08T02:15:00Z")
        self.assertEqual(mapped[0]["id"], "hackernews|123")
        self.assertTrue(mapped[0]["attribution_required"])

    def test_all_approved_captures_validate_without_network(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--validate-only",
                "--json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], "discovery.v1")
        self.assertEqual(payload["source"], "book-discovery-data")
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["skipped"], [])
        self.assertEqual(len(payload["results"]), 8)
        self.assertTrue(all(row["record_count"] > 0 for row in payload["results"]))
        self.assertTrue(SOURCE_ROOT.is_dir())


if __name__ == "__main__":
    unittest.main()
