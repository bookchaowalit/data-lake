#!/usr/bin/env python3
"""Offline guard for draft scraping contracts and redacted fixtures."""

from __future__ import annotations

import csv
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = ROOT / "systems" / "architecture" / "scraping-contracts"
FIXTURE_ROOT = ROOT / "infra" / "tests" / "fixtures" / "scraping_contracts"
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.ingest_scraping_captures import CAPTURES, ingest_capture, main as replay_main  # noqa: E402


class ScrapingSourceContractTests(unittest.TestCase):
    CONTRACTS = {
        "marketplace": ("marketplace.v1.yaml", "marketplace.json", "marketplace.v1"),
        "restaurant": ("restaurant.v1.yaml", "restaurant.json", "restaurant.v1"),
        "ai-tools": ("ai-tools.v1.yaml", "ai-tools.json", "ai_tools.v1"),
        "directory": ("directory.v1.yaml", "directory.json", "directory.v1"),
        "property": ("property.v1.yaml", "property.json", "property.v1"),
    }

    def test_draft_contracts_match_redacted_offline_fixtures(self) -> None:
        for name, (contract_name, fixture_name, schema_version) in self.CONTRACTS.items():
            with self.subTest(contract=name):
                contract = yaml.safe_load((CONTRACT_ROOT / contract_name).read_text(encoding="utf-8"))
                fixture = json.loads((FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8"))
                self.assertEqual(contract["status"], "draft")
                self.assertEqual(contract["collection_approval"], "pending_operator_approval")
                self.assertTrue(contract["not_yet_approved_for_collection"])
                self.assertEqual(contract["schema_version"], schema_version)
                self.assertEqual(fixture["schema_version"], schema_version)
                self.assertTrue(set(contract["quality"]["required"]).issubset(fixture))
                self.assertNotIn("password", fixture)
                self.assertNotIn("api_key", fixture)
                self.assertNotIn("token", fixture)

    def test_ai_tools_raw_fixture_matches_snapshot_and_history_replay_without_writes(self) -> None:
        contract = yaml.safe_load((CONTRACT_ROOT / "ai-tools.v1.yaml").read_text(encoding="utf-8"))
        fixture = json.loads((FIXTURE_ROOT / "ai-tools.json").read_text(encoding="utf-8"))
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fixture.keys())
        writer.writeheader()
        writer.writerow(fixture)
        for spec in (spec for spec in CAPTURES if spec.product == "ai_tools"):
            with self.subTest(dataset=spec.dataset):
                fields = contract["identity"]["history_fields" if spec.history else "fields"]
                self.assertEqual(list(spec.id_fields), fields)
                self.assertEqual(spec.event_time_field, "observed_at")
                self.assertEqual(spec.domain, contract["domain"])
                result = ingest_capture(
                    spec, lake_uri="fixture-unused", validate_only=True, raw_override=output.getvalue().encode()
                )
                self.assertTrue(result["validated"])
                self.assertEqual(result["record_count"], 1)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(replay_main(["--product", "ai_tools"]), 1)


if __name__ == "__main__":
    unittest.main()
