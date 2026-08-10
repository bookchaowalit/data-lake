#!/usr/bin/env python3
"""Offline E2E contract test for the Track B ``job.v1`` product."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[3]
PRODUCT = Path(
    os.environ.get(
        "BOOK_JOB_DATA_ROOT",
        "projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-job-data",
    )
)
if not PRODUCT.is_absolute():
    PRODUCT = (ROOT / PRODUCT).resolve()
PRODUCT_SRC = PRODUCT / "src"
FIXTURE = PRODUCT / "fixtures/job_postings.csv"

sys.path.insert(0, str(PRODUCT_SRC))
sys.path.insert(0, str(ROOT / "infra/scripts"))
sys.path.insert(0, str(ROOT / "infra/scripts/utils"))

from book_job_data import config  # noqa: E402
from book_job_data.ingest import ingest_capture  # noqa: E402
from job_client import fetch_jobs  # noqa: E402


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get_json(url: str) -> dict:
    with urlopen(url, timeout=5) as response:  # noqa: S310 - local test server only
        return json.loads(response.read().decode("utf-8"))


class JobDataE2ETests(unittest.TestCase):
    def test_fixture_bronze_api_and_consumer_boundary(self) -> None:
        try:
            import duckdb  # noqa: F401
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("pyarrow/duckdb not installed")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lake_uri = root / "lake"
            projection_dir = root / "projection"
            config.DATA_DIR = projection_dir

            ingest_result = ingest_capture(
                FIXTURE,
                data_lake_uri=str(lake_uri),
                provider="fixture",
            )
            snapshot = ingest_result["snapshot"]
            self.assertEqual(
                (lake_uri / snapshot["raw_key"]).read_bytes(),
                FIXTURE.read_bytes(),
            )
            self.assertTrue((lake_uri / snapshot["bronze_key"]).is_file())
            self.assertTrue((lake_uri / snapshot["manifest_key"]).is_file())
            self.assertFalse(list(projection_dir.glob("*.csv")))

            port = free_port()
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": os.pathsep.join(
                        (str(PRODUCT_SRC), str(ROOT / "infra/scripts"))
                    ),
                    "SOLO_EMPIRE_DATA_LAKE_URI": str(lake_uri),
                    "DATA_DIR": str(projection_dir),
                    "API_HOST": "127.0.0.1",
                    "API_PORT": str(port),
                    "LAKE_READ_MODE": "parquet",
                    "LAKE_READ_FALLBACK": "error",
                }
            )
            process = subprocess.Popen(
                [sys.executable, "-m", "book_job_data.api"],
                cwd=PRODUCT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            base_url = f"http://127.0.0.1:{port}"
            try:
                deadline = time.monotonic() + 10
                while True:
                    try:
                        health = get_json(f"{base_url}/healthz")
                        break
                    except (URLError, ConnectionError):
                        if process.poll() is not None:
                            stderr = process.stderr.read() if process.stderr else ""
                            self.fail(f"job API exited before health check: {stderr}")
                        if time.monotonic() >= deadline:
                            self.fail("job API did not become ready within 10 seconds")
                        time.sleep(0.1)

                self.assertEqual(health["status"], "ok")
                self.assertEqual(health["storage_model"], "lake_first_job_bronze_duckdb")

                metadata = get_json(f"{base_url}/v1/metadata")
                self.assertEqual(metadata["schema_version"], "job.v1")
                self.assertEqual(metadata["source"], "book-job-data")
                self.assertEqual(metadata["items"][0]["records_source_kind"], "bronze_parquet")
                self.assertEqual(metadata["items"][0]["dataset_counts"]["job_postings"], 2)

                records = get_json(f"{base_url}/v1/records?dataset=job_postings")
                self.assertEqual(records["data_status"], "ok")
                self.assertEqual(len(records["items"]), 2)
                self.assertTrue(all(item.get("source_record_id") for item in records["items"]))
                self.assertTrue(all(item.get("raw_object_key") for item in records["items"]))

                history = get_json(
                    f"{base_url}/v1/history?dataset=job_postings_history"
                )
                self.assertEqual(history["data_status"], "ok")
                self.assertEqual(len(history["items"]), 2)

                consumer_result = fetch_jobs(
                    base_url=base_url,
                    dataset="job_postings",
                    use_lake_fallback=False,
                )
                self.assertEqual(consumer_result.source, "api")
                self.assertEqual(consumer_result.data_status, "ok")
                self.assertEqual(len(consumer_result.items), 2)

                request = Request(f"{base_url}/v1/refresh", method="POST")
                try:
                    urlopen(request, timeout=5)  # noqa: S310 - local test server only
                except HTTPError as exc:
                    self.assertEqual(exc.code, 403)
                    exc.close()
                else:
                    self.fail("POST /v1/refresh unexpectedly succeeded")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()

            # CSV is expected only as the immutable landing payload. The API
            # must not create or read a projection under the product data dir.
            self.assertFalse(list(projection_dir.rglob("*.csv")))


if __name__ == "__main__":
    unittest.main()
