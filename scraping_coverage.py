#!/usr/bin/env python3
"""Audit scraping/source-product coverage from requirement to lake delivery.

The audit is local and read-only. It joins the root requirements registry with
the nested scraper scheduler registry, current crontab tags, capture-file
freshness, local lake evidence, and versioned contract files. It never reads
raw records, credentials, environment files, or remote provider data.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REQUIREMENTS = ROOT / "systems" / "ai-data" / "scraping-data-coverage.yaml"
SCHEMA_VERSION = "solo-empire.scraping-data-coverage.v1"
READY_SOURCE_STATUSES = {"active", "migrated"}
READY_PERMISSION_STATUSES = {"approved", "bounded"}
ALLOWED_PRIORITIES = {"P0", "P1", "P2"}
SENSITIVE_PATH_PARTS = {".env", "credentials", "credential", "secrets", "secret"}


class CoverageConfigError(ValueError):
    """Raised when a required registry cannot be loaded safely."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_now(value: str | None) -> datetime:
    if not value:
        return _utc_now()
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _load_yaml(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise CoverageConfigError(f"missing {label}: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CoverageConfigError(f"invalid YAML in {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CoverageConfigError(f"{label} must be a YAML mapping: {path}")
    return payload


def _relative_input(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def _safe_pattern(pattern: Any) -> bool:
    if not isinstance(pattern, str) or not pattern.strip():
        return False
    pure = PurePosixPath(pattern)
    lowered = {part.lower() for part in pure.parts}
    return not pure.is_absolute() and ".." not in pure.parts and not (lowered & SENSITIVE_PATH_PARTS)


def _source_rows(source_registry: dict[str, Any]) -> list[dict[str, Any]]:
    rows = source_registry.get("sources", [])
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def validate_config(
    config: dict[str, Any], source_registry: dict[str, Any] | None = None
) -> list[str]:
    """Validate ownership, source mapping, evidence paths, and gap actions."""
    errors: list[str] = []
    if config.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    registry_cfg = config.get("source_registry")
    if not isinstance(registry_cfg, dict) or not _safe_pattern(registry_cfg.get("path")):
        errors.append("source_registry.path must be a safe repository-relative path")

    products = config.get("products")
    if not isinstance(products, list) or not products:
        return errors + ["products must be a non-empty list"]

    product_ids: set[str] = set()
    mapped_jobs: dict[str, str] = {}
    for index, product in enumerate(products, 1):
        if not isinstance(product, dict):
            errors.append(f"products[{index}] must be a mapping")
            continue
        product_id = product.get("id")
        if not isinstance(product_id, str) or not product_id.strip():
            errors.append(f"products[{index}] missing id")
            continue
        if product_id in product_ids:
            errors.append(f"duplicate product id: {product_id}")
        product_ids.add(product_id)

        for field in ("name", "domain", "decision", "owner", "retention", "next_action"):
            if not isinstance(product.get(field), str) or not product[field].strip():
                errors.append(f"{product_id}: missing {field}")
        if product.get("priority") not in ALLOWED_PRIORITIES:
            errors.append(f"{product_id}: priority must be P0, P1, or P2")
        consumers = product.get("consumers")
        if not isinstance(consumers, list) or not consumers:
            errors.append(f"{product_id}: consumers must be non-empty")

        permission = product.get("permission")
        if not isinstance(permission, dict):
            errors.append(f"{product_id}: permission must be declared")
        else:
            for field in ("status", "classification", "basis"):
                if not isinstance(permission.get(field), str) or not permission[field].strip():
                    errors.append(f"{product_id}: permission.{field} is required")

        sources = product.get("sources", [])
        if not isinstance(sources, list):
            errors.append(f"{product_id}: sources must be a list")
            sources = []
        if product.get("required", True) and not sources and not product.get("inventory_gap"):
            errors.append(f"{product_id}: source-less requirement must set inventory_gap: true")
        for source in sources:
            if not isinstance(source, dict):
                errors.append(f"{product_id}: source rows must be mappings")
                continue
            job = source.get("job")
            if not isinstance(job, str) or not job.strip():
                errors.append(f"{product_id}: source row missing job")
                continue
            if job in mapped_jobs:
                errors.append(f"source job {job} is mapped by both {mapped_jobs[job]} and {product_id}")
            mapped_jobs[job] = product_id
            capture = source.get("capture")
            if not isinstance(capture, dict):
                errors.append(f"{product_id}/{job}: capture evidence is required")
                continue
            paths = capture.get("paths")
            if not isinstance(paths, list) or not paths:
                errors.append(f"{product_id}/{job}: capture.paths must be non-empty")
            else:
                for pattern in paths:
                    if not _safe_pattern(pattern):
                        errors.append(f"{product_id}/{job}: unsafe capture path {pattern!r}")
            if not isinstance(capture.get("max_age_hours"), (int, float)) or capture["max_age_hours"] <= 0:
                errors.append(f"{product_id}/{job}: capture.max_age_hours must be positive")

        for tag in product.get("cron_tags", []):
            if not isinstance(tag, str) or not tag.strip():
                errors.append(f"{product_id}: cron_tags must contain non-empty strings")

        lake = product.get("lake")
        if not isinstance(lake, dict):
            errors.append(f"{product_id}: lake target must be declared")
        else:
            datasets = lake.get("datasets", [])
            if lake.get("required", True) and (not isinstance(datasets, list) or not datasets):
                errors.append(f"{product_id}: required lake target needs datasets")
            for dataset in datasets if isinstance(datasets, list) else []:
                if not isinstance(dataset, dict) or not isinstance(dataset.get("id"), str):
                    errors.append(f"{product_id}: invalid lake dataset row")
                    continue
                paths = dataset.get("paths")
                if not isinstance(paths, list) or not paths:
                    errors.append(f"{product_id}/{dataset.get('id')}: lake paths must be non-empty")
                else:
                    for pattern in paths:
                        if not _safe_pattern(pattern):
                            errors.append(f"{product_id}/{dataset.get('id')}: unsafe lake path {pattern!r}")
                if not isinstance(dataset.get("max_age_hours"), (int, float)) or dataset["max_age_hours"] <= 0:
                    errors.append(f"{product_id}/{dataset.get('id')}: max_age_hours must be positive")

        delivery = product.get("delivery")
        if not isinstance(delivery, dict) or not isinstance(delivery.get("kind"), str):
            errors.append(f"{product_id}: delivery.kind is required")
        elif delivery.get("contract_path") and not _safe_pattern(delivery.get("contract_path")):
            errors.append(f"{product_id}: unsafe delivery.contract_path")

    if source_registry is not None:
        registry_jobs = {
            row.get("job")
            for row in _source_rows(source_registry)
            if isinstance(row.get("job"), str)
        }
        missing_mappings = sorted(registry_jobs - set(mapped_jobs))
        unknown_jobs = sorted(set(mapped_jobs) - registry_jobs)
        if missing_mappings:
            errors.append("unmapped source registry jobs: " + ", ".join(missing_mappings))
        if unknown_jobs:
            errors.append("unknown source jobs in requirements: " + ", ".join(unknown_jobs))
    return errors


def _evidence(root: Path, paths: list[str], max_age_hours: float, now: datetime) -> dict[str, Any]:
    files: dict[str, Path] = {}
    for pattern in paths:
        if not _safe_pattern(pattern):
            continue
        for candidate in root.glob(pattern):
            if candidate.is_file():
                files[str(candidate.resolve())] = candidate
    if not files:
        return {
            "status": "missing",
            "path": None,
            "modified_at": None,
            "age_hours": None,
            "max_age_hours": max_age_hours,
            "matched_files": 0,
        }
    newest = max(files.values(), key=lambda item: item.stat().st_mtime)
    modified = datetime.fromtimestamp(newest.stat().st_mtime, tz=timezone.utc)
    age_hours = max(0.0, (now - modified).total_seconds() / 3600)
    return {
        "status": "fresh" if age_hours <= max_age_hours else "stale",
        "path": newest.relative_to(root).as_posix(),
        "modified_at": modified.isoformat(),
        "age_hours": round(age_hours, 1),
        "max_age_hours": max_age_hours,
        "matched_files": len(files),
    }


def _read_crontab() -> tuple[str, str]:
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "", "unavailable"
    if result.returncode == 0:
        return result.stdout, "available"
    if "no crontab" in result.stderr.lower():
        return "", "empty"
    return "", "unavailable"


def _contract_evidence(root: Path, delivery: dict[str, Any]) -> dict[str, Any]:
    contract_path = delivery.get("contract_path")
    expected = delivery.get("schema_version")
    if not contract_path:
        return {"status": "missing", "path": None, "schema_version": expected}
    path = root / str(contract_path)
    if not path.is_file():
        return {"status": "missing", "path": str(contract_path), "schema_version": expected}
    text = path.read_text(encoding="utf-8")
    status = "present" if not expected or str(expected) in text else "mismatch"
    return {"status": status, "path": str(contract_path), "schema_version": expected}


def _probe_local_port(port: Any, enabled: bool) -> str:
    if not isinstance(port, int):
        return "not_applicable"
    if not enabled:
        return "not_checked"
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.15):
            return "listening"
    except OSError:
        return "not_listening"


def _aggregate_evidence(items: list[dict[str, Any]], required: bool = True) -> str:
    if not items:
        return "missing" if required else "not_required"
    statuses = [item.get("status") for item in items]
    if all(status == "fresh" for status in statuses):
        return "fresh"
    if any(status == "fresh" for status in statuses):
        return "partial"
    if any(status == "stale" for status in statuses):
        return "stale"
    return "missing"


def _percent(value: int, total: int) -> float:
    return round((value / total) * 100, 1) if total else 0.0


def build_report(
    root: Path = ROOT,
    requirements_path: Path | None = None,
    source_registry_path: Path | None = None,
    *,
    crontab_text: str | None = None,
    crontab_status: str | None = None,
    now: datetime | None = None,
    probe_api: bool = False,
) -> dict[str, Any]:
    """Build a redacted, evidence-backed coverage report."""
    root = root.resolve()
    now = (now or _utc_now()).astimezone(timezone.utc)
    requirements_path = (requirements_path or DEFAULT_REQUIREMENTS).resolve()
    config = _load_yaml(requirements_path, "scraping coverage requirements")
    configured_source_path = Path(str(config.get("source_registry", {}).get("path", "")))
    source_registry_path = _relative_input(root, source_registry_path or configured_source_path).resolve()
    source_registry = _load_yaml(source_registry_path, "nested source coverage registry")
    validation_errors = validate_config(config, source_registry)

    source_by_job = {
        str(row["job"]): row
        for row in _source_rows(source_registry)
        if isinstance(row.get("job"), str)
    }
    if crontab_text is None:
        crontab_text, detected_status = _read_crontab()
        crontab_status = crontab_status or detected_status
    else:
        crontab_status = crontab_status or "provided"

    products: list[dict[str, Any]] = []
    source_matrix: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    priority_rank = {"P0": 0, "P1": 1, "P2": 2}

    for product in config.get("products", []):
        if not isinstance(product, dict):
            continue
        product_id = str(product.get("id", "invalid"))
        priority = str(product.get("priority", "P2"))
        cron_tags = [str(tag) for tag in product.get("cron_tags", []) if isinstance(tag, str)]
        cron_matches = [tag for tag in cron_tags if tag in (crontab_text or "")]
        cron_state = "present" if cron_matches else ("not_required" if not cron_tags else "missing")
        source_results: list[dict[str, Any]] = []

        for source_spec in product.get("sources", []):
            if not isinstance(source_spec, dict):
                continue
            job = str(source_spec.get("job", ""))
            registry_row = source_by_job.get(job)
            capture_cfg = source_spec.get("capture", {})
            capture = _evidence(
                root,
                [str(path) for path in capture_cfg.get("paths", [])],
                float(capture_cfg.get("max_age_hours", 1)),
                now,
            )
            registry_status = str(registry_row.get("status")) if registry_row else "missing"
            quality_status = str(source_spec.get("quality_status", "verified"))
            if registry_status not in READY_SOURCE_STATUSES:
                operational = "blocked" if registry_status in {"blocked", "planned"} else "missing_registry"
            elif quality_status not in {"verified", "accepted"}:
                operational = "degraded"
            else:
                operational = "ready"
            row = {
                "product_id": product_id,
                "job": job,
                "business": registry_row.get("business") if registry_row else product.get("domain"),
                "source": registry_row.get("source") if registry_row else None,
                "channel": registry_row.get("channel") if registry_row else None,
                "schedule": registry_row.get("schedule") if registry_row else None,
                "registry_status": registry_status,
                "owner_repository": registry_row.get("owner_repository") if registry_row else None,
                "quality_status": quality_status,
                "quality_note": source_spec.get("quality_note"),
                "capture": capture,
                "cron_status": cron_state,
                "operational_status": operational,
            }
            source_results.append(row)
            source_matrix.append(row)

        permission = product.get("permission", {})
        permission_status = str(permission.get("status", "unknown"))
        if not source_results:
            collection_status = "missing_inventory"
        elif all(row["operational_status"] == "ready" for row in source_results):
            collection_status = "ready"
        elif any(row["operational_status"] == "ready" for row in source_results):
            collection_status = "partial"
        elif any(row["operational_status"] == "blocked" for row in source_results):
            collection_status = "blocked"
        else:
            collection_status = "unavailable"

        capture_status = _aggregate_evidence(
            [row["capture"] for row in source_results], required=bool(product.get("required", True))
        )
        lake_cfg = product.get("lake", {})
        lake_datasets: list[dict[str, Any]] = []
        for dataset in lake_cfg.get("datasets", []):
            if not isinstance(dataset, dict):
                continue
            evidence = _evidence(
                root,
                [str(path) for path in dataset.get("paths", [])],
                float(dataset.get("max_age_hours", 1)),
                now,
            )
            lake_datasets.append({"id": dataset.get("id"), **evidence})
        lake_status = _aggregate_evidence(lake_datasets, required=bool(lake_cfg.get("required", True)))
        delivery = product.get("delivery", {})
        contract = _contract_evidence(root, delivery)
        api_status = _probe_local_port(delivery.get("api_port"), probe_api)
        required = bool(product.get("required", True))
        end_to_end = (
            required
            and collection_status == "ready"
            and permission_status in READY_PERMISSION_STATUSES
            and cron_state in {"present", "not_required"}
            and capture_status == "fresh"
            and lake_status == "fresh"
            and contract["status"] == "present"
        )
        if not required:
            stage = "supporting_control"
        elif collection_status in {"missing_inventory", "blocked", "unavailable"}:
            stage = "collection_gap"
        elif collection_status == "partial" or permission_status not in READY_PERMISSION_STATUSES:
            stage = "collection_partial"
        elif cron_state == "missing":
            stage = "schedule_gap"
        elif capture_status == "stale":
            stage = "capture_stale"
        elif capture_status != "fresh":
            stage = "capture_gap"
        elif lake_status == "stale":
            stage = "lake_stale"
        elif lake_status != "fresh":
            stage = "capture_only"
        elif contract["status"] != "present":
            stage = "contract_gap"
        else:
            stage = "end_to_end"

        latest_capture_at = max(
            (row["capture"]["modified_at"] for row in source_results if row["capture"]["modified_at"]),
            default=None,
        )
        product_row = {
            "id": product_id,
            "name": product.get("name"),
            "domain": product.get("domain"),
            "priority": priority,
            "required": required,
            "decision": product.get("decision"),
            "owner": product.get("owner"),
            "consumers": product.get("consumers", []),
            "grain": product.get("grain"),
            "retention": product.get("retention"),
            "permission": permission,
            "source_jobs": [row["job"] for row in source_results],
            "access_methods": sorted({str(row["channel"]) for row in source_results if row["channel"]}),
            "schedules": sorted({str(row["schedule"]) for row in source_results if row["schedule"]}),
            "source_status": collection_status,
            "cron_status": cron_state,
            "capture_status": capture_status,
            "latest_capture_at": latest_capture_at,
            "lake_status": lake_status,
            "lake_datasets": lake_datasets,
            "contract": contract,
            "api_status": api_status,
            "stage": stage,
            "end_to_end_ready": end_to_end,
            "next_action": product.get("next_action"),
        }
        products.append(product_row)

        issue_specs: list[tuple[str, bool, str]] = [
            ("source_inventory", collection_status == "missing_inventory", "No source job is mapped"),
            ("collection", collection_status not in {"ready", "missing_inventory"}, f"Collection is {collection_status}"),
            ("permission", permission_status not in READY_PERMISSION_STATUSES, f"Permission is {permission_status}"),
            ("schedule", bool(cron_tags) and cron_state != "present", "Expected cron tag is missing"),
            ("capture", capture_status != "fresh", f"Capture evidence is {capture_status}"),
            ("lake", bool(lake_cfg.get("required", True)) and lake_status != "fresh", f"Lake evidence is {lake_status}"),
            ("contract", required and contract["status"] != "present", f"Contract is {contract['status']}"),
        ]
        if required:
            for code, condition, detail in issue_specs:
                if condition:
                    gaps.append(
                        {
                            "priority": priority,
                            "product_id": product_id,
                            "code": code,
                            "detail": detail,
                            "owner": product.get("owner"),
                            "next_action": product.get("next_action"),
                        }
                    )

    required_products = [row for row in products if row["required"]]
    total_required = len(required_products)
    source_rows = _source_rows(source_registry)
    mapped_jobs = {row["job"] for row in source_matrix}
    registry_jobs = {str(row.get("job")) for row in source_rows if row.get("job")}
    status_counts: dict[str, int] = {}
    for row in source_rows:
        status = str(row.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1

    metrics = {
        "inventory_mapped": sum(1 for row in required_products if row["source_jobs"]),
        "collection_ready": sum(1 for row in required_products if row["source_status"] == "ready"),
        "permission_ready": sum(
            1 for row in required_products if row["permission"].get("status") in READY_PERMISSION_STATUSES
        ),
        "schedule_ready": sum(
            1 for row in required_products if row["cron_status"] in {"present", "not_required"}
        ),
        "fresh_capture": sum(1 for row in required_products if row["capture_status"] == "fresh"),
        "lake_fresh": sum(1 for row in required_products if row["lake_status"] == "fresh"),
        "contract_ready": sum(1 for row in required_products if row["contract"]["status"] == "present"),
        "end_to_end_ready": sum(1 for row in required_products if row["end_to_end_ready"]),
    }
    summary = {
        "required_products": total_required,
        **metrics,
        "inventory_coverage_pct": _percent(metrics["inventory_mapped"], total_required),
        "collection_ready_pct": _percent(metrics["collection_ready"], total_required),
        "permission_ready_pct": _percent(metrics["permission_ready"], total_required),
        "schedule_ready_pct": _percent(metrics["schedule_ready"], total_required),
        "fresh_capture_pct": _percent(metrics["fresh_capture"], total_required),
        "lake_fresh_pct": _percent(metrics["lake_fresh"], total_required),
        "contract_ready_pct": _percent(metrics["contract_ready"], total_required),
        "end_to_end_ready_pct": _percent(metrics["end_to_end_ready"], total_required),
        "source_registry_jobs": len(registry_jobs),
        "mapped_source_jobs": len(registry_jobs & mapped_jobs),
        "source_job_mapping_pct": _percent(len(registry_jobs & mapped_jobs), len(registry_jobs)),
        "source_status_counts": dict(sorted(status_counts.items())),
        "p0_gaps": sum(1 for gap in gaps if gap["priority"] == "P0"),
        "p1_gaps": sum(1 for gap in gaps if gap["priority"] == "P1"),
        "p2_gaps": sum(1 for gap in gaps if gap["priority"] == "P2"),
    }
    gaps.sort(key=lambda item: (priority_rank.get(item["priority"], 9), item["product_id"], item["code"]))
    report = {
        "contract": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "requirements_path": requirements_path.relative_to(root).as_posix()
        if requirements_path.is_relative_to(root)
        else str(requirements_path),
        "source_registry_path": source_registry_path.relative_to(root).as_posix()
        if source_registry_path.is_relative_to(root)
        else str(source_registry_path),
        "scope": config.get("scope", {}),
        "safety": {
            "network": "local-loopback-probe-only" if probe_api else "not-used",
            "credentials": "not-read",
            "raw_records": "not-read",
            "crontab": crontab_status,
        },
        "validation_errors": validation_errors,
        "summary": summary,
        "products": products,
        "source_jobs": sorted(source_matrix, key=lambda row: (str(row["business"]), row["job"])),
        "gaps": gaps,
        "excluded_ingress": config.get("excluded_ingress", []),
    }
    return _json_safe(report)


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value) or "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Scraping and Source-Product Data Coverage",
        "",
        f"Generated: `{report['generated_at']}`  ",
        f"Contract: `{report['contract']}`  ",
        "Evidence boundary: local metadata, file timestamps, crontab tags, lake parts, and contract files only; raw records and credentials are not read.",
        "",
        "## Coverage summary",
        "",
        "| Gate | Ready | Required | Coverage |",
        "|---|---:|---:|---:|",
    ]
    gates = [
        ("Requirement has mapped source", "inventory_mapped", "inventory_coverage_pct"),
        ("Collection ready", "collection_ready", "collection_ready_pct"),
        ("Permission ready", "permission_ready", "permission_ready_pct"),
        ("Schedule ready", "schedule_ready", "schedule_ready_pct"),
        ("Capture fresh", "fresh_capture", "fresh_capture_pct"),
        ("Lake fresh", "lake_fresh", "lake_fresh_pct"),
        ("Contract ready", "contract_ready", "contract_ready_pct"),
        ("End-to-end ready", "end_to_end_ready", "end_to_end_ready_pct"),
    ]
    for label, count_key, pct_key in gates:
        lines.append(f"| {label} | {summary[count_key]} | {summary['required_products']} | {summary[pct_key]:.1f}% |")
    lines.extend(
        [
            "",
            f"Scheduler registry mapping: **{summary['mapped_source_jobs']}/{summary['source_registry_jobs']} ({summary['source_job_mapping_pct']:.1f}%)**. "
            "This proves inventory mapping only; it is not the end-to-end percentage.",
            "",
            "## Requirement-to-delivery matrix",
            "",
            "| Priority | Requirement / decision | Owner | Permission | Access | Source jobs | Cron | Capture | Lake | Contract | API | Stage |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for product in report["products"]:
        if not product["required"]:
            continue
        decision = f"{product['name']} — {product['decision']}"
        contract = product["contract"]
        contract_cell = contract["schema_version"] or contract["status"]
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    product["priority"],
                    decision,
                    product["owner"],
                    product["permission"].get("status"),
                    product["access_methods"],
                    product["source_jobs"],
                    product["cron_status"],
                    f"{product['capture_status']} ({product['latest_capture_at'] or 'no evidence'})",
                    product["lake_status"],
                    f"{contract_cell}: {contract['status']}",
                    product["api_status"],
                    product["stage"],
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Source-job evidence",
            "",
            "| Business | Job | Source | Access | Schedule | Registry | Cron | Capture | Last evidence | Quality |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in report["source_jobs"]:
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    row["business"],
                    row["job"],
                    row["source"],
                    row["channel"],
                    row["schedule"],
                    row["registry_status"],
                    row["cron_status"],
                    row["capture"]["status"],
                    row["capture"]["modified_at"],
                    row["quality_status"],
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Owned gaps",
            "",
            "| Priority | Product | Gate | Evidence | Owner | Next action |",
            "|---|---|---|---|---|---|",
        ]
    )
    for gap in report["gaps"]:
        lines.append(
            "| "
            + " | ".join(
                _cell(gap[key])
                for key in ("priority", "product_id", "code", "detail", "owner", "next_action")
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Explicitly non-scraping ingress",
            "",
            "| Data | Required access path | Reason |",
            "|---|---|---|",
        ]
    )
    for item in report.get("excluded_ingress", []):
        lines.append(
            f"| {_cell(item.get('id'))} | {_cell(item.get('access'))} | {_cell(item.get('reason'))} |"
        )
    if report["validation_errors"]:
        lines.extend(["", "## Validation errors", ""])
        lines.extend(f"- {error}" for error in report["validation_errors"])
    return "\n".join(lines) + "\n"


def render_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    return "\n".join(
        [
            "Scraping / source-product coverage",
            "=" * 72,
            f"Requirements: {summary['required_products']}",
            f"Source jobs mapped: {summary['mapped_source_jobs']}/{summary['source_registry_jobs']} ({summary['source_job_mapping_pct']:.1f}%)",
            f"Requirements with source inventory: {summary['inventory_mapped']}/{summary['required_products']} ({summary['inventory_coverage_pct']:.1f}%)",
            f"Collection ready: {summary['collection_ready']}/{summary['required_products']} ({summary['collection_ready_pct']:.1f}%)",
            f"Permission ready: {summary['permission_ready']}/{summary['required_products']} ({summary['permission_ready_pct']:.1f}%)",
            f"Schedule ready: {summary['schedule_ready']}/{summary['required_products']} ({summary['schedule_ready_pct']:.1f}%)",
            f"Fresh capture: {summary['fresh_capture']}/{summary['required_products']} ({summary['fresh_capture_pct']:.1f}%)",
            f"Fresh lake: {summary['lake_fresh']}/{summary['required_products']} ({summary['lake_fresh_pct']:.1f}%)",
            f"Contract ready: {summary['contract_ready']}/{summary['required_products']} ({summary['contract_ready_pct']:.1f}%)",
            f"End-to-end ready: {summary['end_to_end_ready']}/{summary['required_products']} ({summary['end_to_end_ready_pct']:.1f}%)",
            f"Gate gaps: P0={summary['p0_gaps']} P1={summary['p1_gaps']} P2={summary['p2_gaps']}",
            f"Validation: {'OK' if not report['validation_errors'] else 'FAILED'}",
        ]
    ) + "\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--source-registry", type=Path)
    parser.add_argument("--now", help="ISO timestamp override for deterministic evidence")
    parser.add_argument("--crontab-file", type=Path, help="Use a fixture instead of current user crontab")
    parser.add_argument("--probe-api", action="store_true", help="Probe loopback ports only; no HTTP or remote call")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--check", action="store_true", help="Fail on registry/config drift, not on owned runtime gaps")
    parser.add_argument("--strict", action="store_true", help="Fail unless every required product is end-to-end ready")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    requirements = _relative_input(root, args.requirements).resolve()
    source_registry = _relative_input(root, args.source_registry).resolve() if args.source_registry else None
    crontab_text = None
    crontab_status = None
    if args.crontab_file:
        crontab_path = _relative_input(root, args.crontab_file)
        crontab_text = crontab_path.read_text(encoding="utf-8")
        crontab_status = "fixture"
    try:
        report = build_report(
            root,
            requirements,
            source_registry,
            crontab_text=crontab_text,
            crontab_status=crontab_status,
            now=_parse_now(args.now),
            probe_api=args.probe_api,
        )
    except (CoverageConfigError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1

    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    markdown = render_markdown(report)
    if args.json_output:
        output = _relative_input(root, args.json_output)
        _write(output, encoded)
    if args.markdown_output:
        output = _relative_input(root, args.markdown_output)
        _write(output, markdown)
    print(encoded if args.json else render_text(report), end="")

    if report["validation_errors"]:
        return 1
    if args.check and report["summary"]["source_job_mapping_pct"] != 100.0:
        return 1
    if args.strict and report["summary"]["end_to_end_ready"] != report["summary"]["required_products"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
