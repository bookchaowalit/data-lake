#!/usr/bin/env python3
"""Search the free-first service and Awesome-list discovery index.

The registry is deliberately local and reviewable. It never creates accounts,
calls providers, provisions infrastructure, or treats a GitHub list as proof
that a service is free. Official access links and re-check notes travel with
each entry so an operator can make the final decision before use.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "utils"))
from _env import PROJECT_ROOT  # noqa: E402


REGISTRY_PATH = PROJECT_ROOT / "systems" / "cloud-platform" / "free-resource-index.json"
VALID_ACCESS_MODELS = {"free-forever", "free-quota", "trial-credit", "self-hosted-oss"}
FREE_ACCESS_MODELS = {"free-forever", "free-quota", "self-hosted-oss"}
REQUIRED_SOURCE_FIELDS = ("id", "name", "url", "focus", "categories", "source_type")
REQUIRED_RESOURCE_FIELDS = (
    "id",
    "name",
    "provider",
    "category",
    "use_cases",
    "access_model",
    "requires_account",
    "official_url",
    "access_url",
    "free_notes",
    "limits",
    "source_ids",
    "tags",
)


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read free resource registry {path}: {exc}") from exc
    errors = validate_registry(data)
    if errors:
        raise ValueError("invalid free resource registry:\n" + "\n".join(errors))
    return data


def validate_registry(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["root must be an object"]

    if not isinstance(data.get("version"), int) or isinstance(data.get("version"), bool):
        errors.append("version must be an integer")

    sources = data.get("awesome_sources")
    if not isinstance(sources, list) or not sources:
        errors.append("awesome_sources must be a non-empty list")
        sources = []
    resources = data.get("resources")
    if not isinstance(resources, list) or not resources:
        errors.append("resources must be a non-empty list")
        resources = []

    source_ids: set[str] = set()
    for index, source in enumerate(sources, 1):
        prefix = f"source {index}"
        if not isinstance(source, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in REQUIRED_SOURCE_FIELDS:
            value = source.get(field)
            if field == "categories":
                if not isinstance(value, list) or not value:
                    errors.append(f"{prefix}: categories must be a non-empty list")
            elif not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}: {field} must be a non-empty string")
        source_id = source.get("id")
        if isinstance(source_id, str) and source_id:
            if source_id in source_ids:
                errors.append(f"{prefix}: duplicate id {source_id!r}")
            source_ids.add(source_id)
        if isinstance(source.get("url"), str) and not source["url"].startswith("https://"):
            errors.append(f"{prefix}: url must use https")

    resource_ids: set[str] = set()
    for index, resource in enumerate(resources, 1):
        prefix = f"resource {index}"
        if not isinstance(resource, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in REQUIRED_RESOURCE_FIELDS:
            if field not in resource:
                errors.append(f"{prefix}: missing {field}")
        resource_id = resource.get("id")
        if isinstance(resource_id, str) and resource_id:
            if resource_id in resource_ids:
                errors.append(f"{prefix}: duplicate id {resource_id!r}")
            resource_ids.add(resource_id)

        if resource.get("access_model") not in VALID_ACCESS_MODELS:
            errors.append(
                f"{prefix}: access_model must be one of {sorted(VALID_ACCESS_MODELS)}"
            )
        if not isinstance(resource.get("requires_account"), bool):
            errors.append(f"{prefix}: requires_account must be a boolean")
        for field in ("use_cases", "source_ids", "tags"):
            value = resource.get(field)
            if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
                errors.append(f"{prefix}: {field} must be a list of non-empty strings")
        for field in ("official_url", "access_url"):
            value = resource.get(field)
            if not isinstance(value, str) or not value.startswith("https://"):
                errors.append(f"{prefix}: {field} must be an https URL")
        for field in ("name", "provider", "category", "free_notes", "limits"):
            value = resource.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}: {field} must be a non-empty string")
        for source_id in resource.get("source_ids", []):
            if source_id not in source_ids:
                errors.append(f"{prefix}: unknown source_id {source_id!r}")

    return errors


def source_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {source["id"]: source for source in registry["awesome_sources"]}


def filter_resources(
    resources: Iterable[dict[str, Any]],
    *,
    query: str | None = None,
    category: str | None = None,
    provider: str | None = None,
    access_model: str | None = None,
    source_id: str | None = None,
    free_only: bool = False,
) -> list[dict[str, Any]]:
    normalized_query = query.lower().strip() if query else None
    result: list[dict[str, Any]] = []
    for resource in resources:
        if category and resource["category"] != category:
            continue
        if provider and resource["provider"] != provider:
            continue
        if access_model and resource["access_model"] != access_model:
            continue
        if source_id and source_id not in resource["source_ids"]:
            continue
        if free_only and resource["access_model"] not in FREE_ACCESS_MODELS:
            continue
        if normalized_query:
            searchable = json.dumps(resource, ensure_ascii=False).lower()
            if normalized_query not in searchable:
                continue
        result.append(resource)
    return sorted(result, key=lambda item: (item["category"], item["name"]))


def render_resources(resources: list[dict[str, Any]], sources: dict[str, dict[str, Any]]) -> str:
    if not resources:
        return "ไม่พบ resource ที่ตรงกับเงื่อนไข"
    lines: list[str] = []
    for resource in resources:
        account = "ต้องมีบัญชี" if resource["requires_account"] else "ไม่ต้องมีบัญชี"
        lines.extend(
            [
                f"[{resource['category']}] {resource['name']} — {resource['provider']}",
                f"Access: {resource['access_model']} | {account}",
                f"Use: {', '.join(resource['use_cases'])}",
                f"Official: {resource['official_url']}",
                f"Access/Pricing: {resource['access_url']}",
                f"Free note: {resource['free_notes']}",
                f"Limits: {resource['limits']}",
                "Awesome: "
                + ", ".join(sources[source_id]["url"] for source_id in resource["source_ids"]),
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def render_sources(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "ไม่พบ Awesome source ที่ตรงกับเงื่อนไข"
    return "\n".join(
        f"{source['id']}\t{source['name']}\t{', '.join(source['categories'])}\t{source['url']}"
        for source in sources
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    check = subparsers.add_parser("check", help="validate the resource registry")
    check.add_argument("--registry", help="optional registry path for tests")
    check.set_defaults(handler=command_check)

    listing = subparsers.add_parser("list", help="list resources")
    add_filters(listing)
    listing.set_defaults(handler=command_list)

    search = subparsers.add_parser("search", help="search resources by name, use case, tag, or note")
    search.add_argument("query")
    add_filters(search)
    search.set_defaults(handler=command_search)

    recommend = subparsers.add_parser("recommend", help="find resources for a use case")
    recommend.add_argument("use_case", help="e.g. hosting, api, sql, auth, email")
    add_filters(recommend)
    recommend.set_defaults(handler=command_search)

    awesome = subparsers.add_parser("awesome", help="list Awesome GitHub discovery sources")
    awesome.add_argument("--category", help="filter sources by covered category")
    awesome.add_argument("--json", action="store_true", help="emit JSON")
    awesome.add_argument("--registry", help="optional registry path for tests")
    awesome.set_defaults(handler=command_awesome)
    return parser


def add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--category", help="filter by category")
    parser.add_argument("--provider", help="filter by provider")
    parser.add_argument("--access-model", choices=sorted(VALID_ACCESS_MODELS))
    parser.add_argument("--source", dest="source_id", help="filter by Awesome source id")
    parser.add_argument("--free-only", action="store_true", help="exclude trial-credit entries")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--registry", help="optional registry path for tests")


def command_check(args: argparse.Namespace) -> int:
    registry = load_registry(Path(args.registry) if args.registry else REGISTRY_PATH)
    categories = {resource["category"] for resource in registry["resources"]}
    print(
        f"OK: validated {len(registry['resources'])} resources, "
        f"{len(categories)} categories, {len(registry['awesome_sources'])} discovery sources"
    )
    return 0


def selected_resources(args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    registry = load_registry(Path(args.registry) if args.registry else REGISTRY_PATH)
    resources = filter_resources(
        registry["resources"],
        query=getattr(args, "query", None) or getattr(args, "use_case", None),
        category=args.category,
        provider=args.provider,
        access_model=args.access_model,
        source_id=args.source_id,
        free_only=args.free_only,
    )
    return registry, resources


def command_list(args: argparse.Namespace) -> int:
    registry, resources = selected_resources(args)
    if args.json:
        print(json.dumps({"resources": resources}, ensure_ascii=False, indent=2))
    else:
        print(render_resources(resources, source_map(registry)))
    return 0


def command_search(args: argparse.Namespace) -> int:
    registry, resources = selected_resources(args)
    if args.json:
        print(json.dumps({"query": args.query if hasattr(args, "query") else args.use_case, "resources": resources}, ensure_ascii=False, indent=2))
    else:
        print(render_resources(resources, source_map(registry)))
    return 0


def command_awesome(args: argparse.Namespace) -> int:
    registry = load_registry(Path(args.registry) if args.registry else REGISTRY_PATH)
    sources = registry["awesome_sources"]
    if args.category:
        sources = [source for source in sources if args.category in source["categories"]]
    if args.json:
        print(json.dumps({"sources": sources}, ensure_ascii=False, indent=2))
    else:
        print(render_sources(sources))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        return args.handler(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
