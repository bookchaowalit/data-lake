"""Conservative matching for public discovery records.

The profile is user-supplied and read-only. A match is a triage signal, never
an eligibility, legal, funding, selection or entitlement determination.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
PROFILE_SCHEMA = ROOT / "systems" / "architecture" / "discovery-profile-v1.json"


def load_profile(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    schema = json.loads(PROFILE_SCHEMA.read_text(encoding="utf-8"))
    if list(Draft202012Validator(schema).iter_errors(value)):
        raise ValueError("profile does not satisfy discovery.profile.v1")
    return value


def _unknown(value: Any) -> bool:
    return value in (None, "unknown", "unverified")


def _add_unknown(missing: list[str], field: str) -> None:
    if field not in missing:
        missing.append(field)


def match_item(item: dict[str, Any], profile: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Return a bounded, explainable triage result without copying profile data."""
    hard: list[str] = []
    missing: list[str] = []
    notes: list[str] = []

    countries = item.get("eligible_countries") or []
    country = profile.get("country")
    if countries and "GLOBAL" not in countries:
        if country is None:
            _add_unknown(missing, "country")
        elif country not in countries:
            hard.append("country is outside the published eligible-country list")
    elif not countries:
        _add_unknown(missing, "eligible_countries")

    terms = item.get("terms") or {}
    study = terms.get("study_level")
    if study is not None:
        if _unknown(profile.get("study_level")):
            _add_unknown(missing, "study_level")
        elif profile.get("study_level") != study:
            hard.append("study level does not match the published program term")
    elif item.get("category") in {"undergraduate", "postgraduate", "vocational", "short-course"}:
        _add_unknown(missing, "study_level")

    applicant = terms.get("applicant_type")
    if applicant in {"individual", "organization"}:
        if _unknown(profile.get("applicant_type")):
            _add_unknown(missing, "applicant_type")
        elif profile.get("applicant_type") != applicant:
            hard.append("applicant type does not match the published program term")

    stage = terms.get("startup_stage")
    if stage and stage != "any":
        if _unknown(profile.get("startup_stage")):
            _add_unknown(missing, "startup_stage")
        elif profile.get("startup_stage") != stage:
            hard.append("startup stage does not match the published program term")

    incorporation = terms.get("incorporation_required")
    if incorporation is True:
        if profile.get("has_legal_entity") is None:
            _add_unknown(missing, "has_legal_entity")
        elif profile.get("has_legal_entity") is False:
            hard.append("a legal entity is published as required")

    if "student" in (item.get("eligibility_text") or "").casefold():
        if _unknown(profile.get("student_status")):
            _add_unknown(missing, "student_status")
        elif profile.get("student_status") == "not_student":
            hard.append("the published text refers to a student condition")

    status = item.get("status")
    deadline = item.get("deadline") or {}
    availability = item.get("availability") or {}
    availability_start = availability.get("starts_at")
    scheduled = False
    days_until_start = None
    if availability_start:
        try:
            start = datetime.fromisoformat(availability_start.replace("Z", "+00:00"))
            scheduled = start > now
            days_until_start = max(0, (start - now).total_seconds() / 86400) if scheduled else 0
        except ValueError:
            _add_unknown(missing, "availability")
    deadline_at = deadline.get("at") if deadline.get("kind") == "fixed" else None
    expired = False
    days_remaining = None
    if deadline_at:
        try:
            target = datetime.fromisoformat(deadline_at.replace("Z", "+00:00"))
            expired = target <= now
            days_remaining = max(0, (target - now).total_seconds() / 86400)
        except ValueError:
            _add_unknown(missing, "deadline")
    else:
        _add_unknown(missing, "deadline")
    if status != "open":
        notes.append("source does not currently declare this record open")
    if scheduled:
        notes.append("published availability starts in the future")
    if expired:
        notes.append("published fixed deadline has passed")

    if "unknown" in (item.get("eligibility_text") or "").casefold():
        _add_unknown(missing, "eligibility_text")
    if (item.get("value") or {}).get("kind") == "unknown":
        _add_unknown(missing, "value")

    if hard:
        result = "not_eligible"
    elif status != "open" or expired or scheduled:
        result = "not_open"
    elif missing:
        result = "unknown"
    else:
        result = "possible"
    return {
        "match": result,
        "reasons": hard + notes,
        "missing_fields": sorted(missing),
        "deadline_at": deadline_at,
        "days_remaining": round(days_remaining, 2) if days_remaining is not None else None,
        "availability_starts_at": availability_start,
        "days_until_start": round(days_until_start, 2) if days_until_start is not None else None,
    }


def enrich(items: list[dict[str, Any]], profile: dict[str, Any], *, now: datetime, deadline_within_days: int | None = None) -> list[dict[str, Any]]:
    if deadline_within_days is not None and deadline_within_days < 0:
        raise ValueError("deadline window must be nonnegative")
    output = []
    for row in items:
        item = row.get("item", row)
        result = match_item(item, profile, now=now)
        if deadline_within_days is not None and (result["days_remaining"] is None or result["days_remaining"] > deadline_within_days):
            continue
        output.append(dict(row, match=result))
    return output
