#!/usr/bin/env python3
"""Publish bounded collection-monitor summaries through the installed Hub CLI.

Only the fixed monitor JSON names are inputs. Raw rows, source paths, free-form
gap descriptions and the original Markdown never enter published artifacts.
Publication QA validates the report, not collection or deployment readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as ReadTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from data_lake.capture_lock import LockBusyError, acquire_lock
from data_lake.collection_health import CollectionHealthError, build_health_report

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPORT_DIR = ROOT / "data" / "generated" / "briefings"
COVERAGE_NAME = "scraping-data-coverage.json"
HEALTH_NAME = "scraping-collection-health.json"
RECEIPT_NAME = "scraping-collection-publication.json"
OUTPUT_CONTRACT = "solo-empire.collection-output.v1"
RECEIPT_CONTRACT = "solo-empire.collection-publication.v1"
TOOL_VERSION = "collection-output.v1"
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_CLI_BYTES = 16 * 1024
MAX_PRODUCTS = 256
MAX_GAPS = 2048
METRICS = {
    "inventory_mapped": "inventory_coverage_pct",
    "collection_ready": "collection_ready_pct",
    "permission_ready": "permission_ready_pct",
    "schedule_ready": "schedule_ready_pct",
    "fresh_capture": "fresh_capture_pct",
    "lake_fresh": "lake_fresh_pct",
    "contract_present": "contract_present_pct",
    "contract_ready": "contract_ready_pct",
}
GAP_ACTIONS = {
    "source_inventory": "เติมรายการแหล่งข้อมูลในทะเบียนที่รับผิดชอบ",
    "source_registry": "ตรวจทะเบียนและหลักฐานของแหล่งข้อมูล",
    "collection": "ตรวจขั้นตอนเก็บข้อมูลและขอบเขตที่ได้รับอนุญาต",
    "permission": "ให้เจ้าของตรวจสิทธิ์การเก็บข้อมูลก่อนเปิดใช้งาน",
    "schedule": "ตรวจตารางรันและการอนุมัติของเครื่องที่ใช้รัน",
    "capture": "ตรวจความสดของหลักฐานการเก็บข้อมูล",
    "lake": "ตรวจข้อมูลและความสดใน lake",
    "contract": "ตรวจสัญญาข้อมูลและสถานะการอนุมัติ",
}


class PublicationError(ValueError):
    """A stable error code; never carries child output or private input."""


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise PublicationError("report_missing_or_unsafe")
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            raise PublicationError("report_too_large")
        payload = json.loads(raw)
    except (OSError, ValueError, RecursionError) as exc:
        if isinstance(exc, PublicationError):
            raise
        raise PublicationError("report_invalid_json") from None
    if not isinstance(payload, dict):
        raise PublicationError("report_invalid_object")
    return payload, raw


def build_output(coverage: dict[str, Any], supplied_health: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    """Derive health afresh, then project only fixed aggregate fields."""
    if not isinstance(coverage.get("gaps"), list) or len(coverage["gaps"]) > MAX_GAPS:
        raise PublicationError("coverage_gaps_invalid")
    try:
        health = build_health_report(coverage, source_report=COVERAGE_NAME)
    except CollectionHealthError:
        raise PublicationError("coverage_contract_invalid") from None
    if health["validation_errors"]:
        raise PublicationError("coverage_validation_failed")
    required = health["summary"]["required_products"]
    if required > MAX_PRODUCTS:
        raise PublicationError("coverage_products_exceed_limit")
    metrics: dict[str, int | float] = {}
    for count_key, percentage_key in METRICS.items():
        source_summary = coverage["summary"]
        if count_key not in source_summary and percentage_key not in source_summary:
            continue
        count, percentage = source_summary.get(count_key), source_summary.get(percentage_key)
        if (
            type(count) is not int or not 0 <= count <= required
            or type(percentage) not in (int, float) or not math.isfinite(percentage)
            or percentage != round(count / required * 100, 1)
        ):
            raise PublicationError("coverage_metrics_inconsistent")
        metrics[count_key], metrics[percentage_key] = count, percentage
    gap_counts = {code: 0 for code in GAP_ACTIONS}
    for gap in health["gaps"]:
        code = gap["code"]
        if code not in gap_counts:
            raise PublicationError("coverage_gap_code_unsupported")
        gap_counts[code] += 1
    health_fields = ("contract", "generated_at", "status", "summary")
    expected = {key: health[key] for key in health_fields}
    # JSON comparison also distinguishes booleans from integer counts.
    try:
        verified = supplied_health is not None and _json_bytes(
            {key: supplied_health.get(key) for key in health_fields}
        ) == _json_bytes(expected)
    except (TypeError, ValueError, RecursionError):
        verified = False
    generated_at = datetime.fromisoformat(health["generated_at"].replace("Z", "+00:00")).isoformat()
    output = {
        "contract": OUTPUT_CONTRACT,
        "source": "scraping_coverage_audit",
        "source_report": COVERAGE_NAME,
        "generated_at": generated_at,
        "runtime_status": health["status"],
        "summary": health["summary"],
        "coverage_metrics": metrics,
        "gap_counts": gap_counts,
        "health": {**expected, "generated_at": generated_at},
        "safety": {
            "raw_records": "excluded", "credentials": "excluded",
            "free_form_text": "excluded", "privacy": "internal",
            "qa_scope": "aggregate-report-only", "cloud_readiness": "not-asserted",
        },
    }
    return output, "verified" if verified else "regenerated"


def render_markdown(output: dict[str, Any]) -> bytes:
    summary = output["summary"]
    lines = [
        "# รายงานสถานะการเก็บข้อมูล", "",
        f"เวลาของหลักฐาน: `{output['generated_at']}`  ",
        f"สถานะการทำงาน: **{output['runtime_status']}**  ",
        f"พร้อมครบวงจร: **{summary['end_to_end_ready']}/{summary['required_products']} ({summary['end_to_end_ready_pct']:.1f}%)**", "",
        "QA accepted หมายถึงรายงานสรุปผ่านการตรวจสอบ การเผยแพร่รายงานไม่ยืนยันว่าตารางรันหรือ deployment พร้อมใช้งาน", "",
        "| เกณฑ์ | จำนวนพร้อม |", "| --- | ---: |",
    ]
    labels = {
        "inventory_mapped": "ทะเบียนแหล่งข้อมูล", "collection_ready": "การเก็บข้อมูล",
        "permission_ready": "สิทธิ์การเก็บข้อมูล", "schedule_ready": "ตารางรัน",
        "fresh_capture": "หลักฐานการเก็บข้อมูลที่สด", "lake_fresh": "ข้อมูล lake ที่สด",
        "contract_present": "มีสัญญาข้อมูล", "contract_ready": "สัญญาข้อมูลพร้อม",
    }
    for key, label in labels.items():
        if key in output["coverage_metrics"]:
            lines.append(f"| {label} | {output['coverage_metrics'][key]}/{summary['required_products']} |")
    lines.extend([
        "", f"ช่องว่างตามลำดับความสำคัญ: P0={summary['p0_gaps']}, P1={summary['p1_gaps']}, P2={summary['p2_gaps']}", "",
        "| ช่องว่าง | จำนวน | ขั้นตอนถัดไป |", "| --- | ---: | --- |",
    ])
    for code, action in GAP_ACTIONS.items():
        count = output["gap_counts"][code]
        if count:
            lines.append(f"| `{code}` | {count} | {action} |")
    if not summary["gap_count"]:
        lines.append("| — | 0 | ติดตามความสดและสถานะต่อเนื่อง |")
    lines.extend([
        "", "รายงานนี้เผยแพร่เฉพาะตัวเลขและสถานะรวม ไม่รวมแถวข้อมูลดิบ ข้อความเอกสารส่วนตัว หรือข้อมูลรับรอง", "",
        "เปิดและดาวน์โหลดผ่านหน้า Production ของ Solo Web เมื่อ API ใช้ Hub home เดียวกับการเผยแพร่", "",
    ])
    return "\n".join(lines).encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _run_cli(command: list[str], timeout_seconds: int) -> bytes:
    """Kill a child that exceeds the time or stdout cap; discard stderr."""
    deadline = time.monotonic() + timeout_seconds
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as child:
            assert child.stdout is not None
            with ThreadPoolExecutor(max_workers=1) as readers:
                reader = readers.submit(child.stdout.read, MAX_CLI_BYTES + 1)
                try:
                    raw = reader.result(timeout=max(0, deadline - time.monotonic()))
                    if len(raw) > MAX_CLI_BYTES:
                        raise PublicationError("hub_receipt_too_large")
                    if child.wait(timeout=max(0, deadline - time.monotonic())):
                        raise PublicationError("hub_import_failed")
                    return raw
                except (ReadTimeout, subprocess.TimeoutExpired):
                    raise PublicationError("hub_import_timeout") from None
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.wait()
    except OSError:
        raise PublicationError("hub_cli_unavailable") from None


def _import_artifact(path: Path, content: bytes, kind: str, hub_home: Path, timeout_seconds: int) -> dict[str, Any]:
    digest = hashlib.sha256(content).hexdigest()
    artifact_id = f"sha256:{digest}"
    command = [
        sys.executable, "-m", "production_hub", "--home", str(hub_home),
        "import-file", str(path), "--kind", kind, "--tool", "external",
        "--tool-version", TOOL_VERSION, "--job", f"scraping-collection-{digest}",
        "--privacy", "internal", "--qa", "accepted",
    ]
    try:
        raw = _run_cli(command, timeout_seconds)
        receipt = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, PublicationError):
            raise
        raise PublicationError("hub_receipt_invalid") from None
    if (
        not isinstance(receipt, dict) or receipt.get("artifact_id") != artifact_id
        or receipt.get("kind") != kind or type(receipt.get("created")) is not bool
    ):
        raise PublicationError("hub_receipt_mismatch")
    destination = hub_home / "store" / "sha256" / digest[:2] / digest
    try:
        with destination.open("rb") as stored:
            stored_content = stored.read(len(content) + 1)
        if stored_content != content:
            raise PublicationError("hub_content_mismatch")
    except OSError:
        raise PublicationError("hub_content_unavailable") from None
    try:
        record = json.loads(_run_cli([
            sys.executable, "-m", "production_hub", "--home", str(hub_home), "show", artifact_id,
        ], timeout_seconds))
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, PublicationError):
            raise
        raise PublicationError("hub_record_invalid") from None
    # Hub deduplication retains the first registration's metadata. Confirm it
    # via the public CLI before claiming privacy/QA for already stored bytes.
    if (
        not isinstance(record, dict) or record.get("schema_version") != "artifact.v1"
        or record.get("artifact_id") != artifact_id or record.get("kind") != kind
        or type(record.get("byte_size")) is not int or record["byte_size"] != len(content)
        or record.get("privacy_class") != "internal"
        or not isinstance(record.get("qa"), dict) or record["qa"].get("status") != "accepted"
        or not isinstance(record.get("producer"), dict)
        or record["producer"].get("tool_id") != "external"
        or record["producer"].get("tool_version") != TOOL_VERSION
    ):
        raise PublicationError("hub_record_metadata_mismatch")
    return {
        "artifact_id": artifact_id, "sha256": digest, "kind": kind,
        "byte_size": len(content), "created": receipt["created"],
        "filename": path.name, "local_destination": str(destination),
        "content_path": f"/api/production/v1/artifacts/{artifact_id}/content",
        "privacy": "internal", "qa_status": "accepted", "metadata_verified": True,
    }


def publish_outputs(report_dir: Path, *, hub_home: Path, timeout_seconds: int = 30) -> dict[str, Any]:
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60:
        raise PublicationError("timeout_out_of_bounds")
    report_dir, hub_home = report_dir.resolve(), hub_home.resolve()
    with acquire_lock(report_dir / "scraping-collection-publication.lock"):
        coverage, coverage_bytes = _read_json(report_dir / COVERAGE_NAME)
        try:
            supplied_health, _ = _read_json(report_dir / HEALTH_NAME)
        except PublicationError:
            supplied_health = None
        try:
            output, health_input = build_output(coverage, supplied_health)
        except (TypeError, ValueError, RecursionError) as exc:
            if isinstance(exc, PublicationError):
                raise
            raise PublicationError("coverage_contract_invalid") from None
        documents = [
            (report_dir / "scraping-collection-output.json", _json_bytes(output), "dataset.table"),
            (report_dir / "scraping-collection-output.md", render_markdown(output), "workflow.plan"),
        ]
        artifacts = []
        for path, content, kind in documents:
            _atomic_write(path, content)
            artifacts.append(_import_artifact(path, content, kind, hub_home, timeout_seconds))
        receipt = {
            "contract": RECEIPT_CONTRACT, "status": "published",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "generated_at": output["generated_at"], "runtime_status": output["runtime_status"],
            "source_report": COVERAGE_NAME, "coverage_sha256": hashlib.sha256(coverage_bytes).hexdigest(),
            "health_input": health_input, "hub_home": str(hub_home),
            "receipt_path": str(report_dir / RECEIPT_NAME), "artifacts": artifacts,
            "consumer": {"application": "solo-web", "page": "/production", "requires_same_hub_home": True},
            "cloud_readiness": "not-asserted",
        }
        _atomic_write(report_dir / RECEIPT_NAME, _json_bytes(receipt))
        return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="เผยแพร่รายงานสรุปการเก็บข้อมูลไปยัง Production Hub ในเครื่อง")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR, help="โฟลเดอร์รายงานจาก collection monitor")
    parser.add_argument("--hub-home", type=Path, required=True, help="ระบุ Hub home ที่รับผิดชอบ โดย API ต้องใช้ home เดียวกัน")
    parser.add_argument("--timeout-seconds", type=int, default=30, help="เวลาสูงสุดต่อคำสั่ง Hub CLI (1–60 วินาที)")
    args = parser.parse_args(argv)
    try:
        receipt = publish_outputs(args.report_dir, hub_home=args.hub_home, timeout_seconds=args.timeout_seconds)
    except (PublicationError, LockBusyError, OSError) as exc:
        code = str(exc) if isinstance(exc, (PublicationError, LockBusyError)) else "publication_io_failed"
        print(json.dumps({"status": "error", "error": code, "receipt_updated": False}))
        return 1
    print(_json_bytes(receipt).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
