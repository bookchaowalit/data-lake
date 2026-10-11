#!/usr/bin/env python3
"""Unsafe native imports stay isolated from the lake control process."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake.engines.native_runtime import probe_embedded_clickhouse  # noqa: E402
from data_lake.engines.clickhouse_engine import ClickHouseLakeEngine  # noqa: E402
from data_lake.engines.base import available_engines  # noqa: E402


class NativeRuntimeTests(unittest.TestCase):
    def test_signal_is_unavailable_without_private_stderr(self):
        with patch("importlib.util.find_spec", return_value=object()), patch(
            "subprocess.run", return_value=subprocess.CompletedProcess([], -4)
        ) as run:
            available, detail = probe_embedded_clickhouse()
        self.assertFalse(available)
        self.assertIn("signal 4", detail)
        self.assertEqual(run.call_args.args[0][0], sys.executable)
        self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assertLessEqual(run.call_args.kwargs["timeout"], 20)

    def test_timeout_is_bounded_and_unavailable(self):
        with patch("importlib.util.find_spec", return_value=object()), patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("chdb", 15)
        ):
            available, detail = probe_embedded_clickhouse()
        self.assertFalse(available)
        self.assertIn("timed out", detail)

    def test_failed_probe_never_imports_native_module_in_parent(self):
        with patch("data_lake.engines.clickhouse_engine.probe_embedded_clickhouse", return_value=(False, "chdb signal 4")), patch(
            "builtins.__import__", side_effect=AssertionError("unsafe import")
        ):
            with self.assertRaisesRegex(RuntimeError, "signal 4"):
                ClickHouseLakeEngine().open()

    def test_availability_reports_native_failure(self):
        with patch("data_lake.engines.base.get_engine", return_value=ClickHouseLakeEngine()), patch(
            "data_lake.engines.clickhouse_engine.probe_embedded_clickhouse", return_value=(False, "chdb signal 4")
        ):
            rows = available_engines()
        self.assertEqual(rows[-1]["status"], "unavailable")
        self.assertIn("signal 4", rows[-1]["detail"])


if __name__ == "__main__":
    unittest.main()
