#!/usr/bin/env python3
"""Plan and operate explicitly approved, current-user Windows scraping tasks."""

from __future__ import annotations

import argparse
import base64
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import sys
from time import gmtime
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "infra" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from data_lake.capture_lock import LockBusyError, acquire_lock

JOBS = ("news", "crypto", "stocks", "fx", "defi", "seo", "monitor")
DEFAULT_LAKE = ROOT / "data" / "lake-local" / "scraping-captures-v2"
LOG_DIR = ROOT / "data" / "logs" / "windows-scraping"
MARKER = "solo-empire.windows-scraping.v1"

POWERSHELL = r"""
$ErrorActionPreference = 'Stop'
try {
    $config = [Console]::In.ReadToEnd() | ConvertFrom-Json
    if ($config.action -notin @('status', 'install', 'remove')) {
        throw 'unsupported_action'
    }
    if ($config.action -ne 'status' -and -not $config.operator_approved) {
        throw 'host_approval_required'
    }
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $existing = @(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop |
        Where-Object { $_.TaskName -in @($config.tasks.name) })
    $rows = @()
    foreach ($spec in $config.tasks) {
        $task = @($existing | Where-Object TaskName -eq $spec.name)
        $matches = $false
        if ($task.Count -eq 1) {
            $task = $task[0]
            $actions = @($task.Actions)
            $triggers = @($task.Triggers)
            $principalMatches = $false
            try {
                $taskUser = $task.Principal.UserId
                if ($taskUser -notmatch '^S-1-') {
                    $taskUser = [System.Security.Principal.NTAccount]::new($taskUser).Translate(
                        [System.Security.Principal.SecurityIdentifier]).Value
                }
                $principalMatches = $taskUser -eq $identity
            } catch [System.Security.Principal.IdentityNotMappedException] {
                $principalMatches = $false
            }
            $triggerMatches = $false
            if ($triggers.Count -eq 1 -and $triggers[0].Enabled) {
                $trigger = $triggers[0]
                if ($spec.interval_hours) {
                    $triggerMatches = (
                        $trigger.CimClass.CimClassName -eq 'MSFT_TaskTimeTrigger' -and
                        $trigger.Repetition.Interval -eq "PT$($spec.interval_hours)H" -and
                        -not $trigger.Repetition.Duration)
                } else {
                    $triggerMatches = (
                        $trigger.CimClass.CimClassName -eq 'MSFT_TaskDailyTrigger' -and
                        $trigger.DaysInterval -eq 1 -and
                        -not $trigger.Repetition.Interval -and
                        ([datetime]$trigger.StartBoundary).ToString('HH:mm') -eq $spec.daily_at)
                }
            }
            $matches = (
                $task.Description -eq $spec.description -and
                $actions.Count -eq 1 -and
                $actions[0].Execute -eq $spec.execute -and
                $actions[0].Arguments -ceq $spec.arguments -and
                $actions[0].WorkingDirectory -eq $spec.working_directory -and
                $principalMatches -and
                $task.Principal.LogonType -eq 'Interactive' -and
                $task.Principal.RunLevel -eq 'Limited' -and
                $task.Settings.MultipleInstances -eq 'IgnoreNew' -and
                $task.Settings.StartWhenAvailable -and
                $task.Settings.ExecutionTimeLimit -eq 'PT15M' -and
                $triggerMatches)
            $info = Get-ScheduledTaskInfo -InputObject $task -ErrorAction Stop
            $rows += [pscustomobject]@{
                job = $spec.job; task_name = $spec.name; installed = $true
                enabled = [bool]$task.Settings.Enabled; definition_matches = [bool]$matches
                last_result = [int64]$info.LastTaskResult
                last_run_time = $info.LastRunTime.ToString('o')
                next_run_time = $info.NextRunTime.ToString('o')
            }
        } else {
            $rows += [pscustomobject]@{
                job = $spec.job; task_name = $spec.name; installed = $false
                enabled = $false; definition_matches = $false
            }
        }
    }
    if ($config.action -eq 'install') {
        if (@($rows | Where-Object installed).Count) { throw 'task_name_collision' }
        $created = @()
        try {
            foreach ($spec in $config.tasks) {
                $action = New-ScheduledTaskAction -Execute $spec.execute `
                    -Argument $spec.arguments -WorkingDirectory $spec.working_directory
                if ($spec.interval_hours) {
                    $trigger = New-ScheduledTaskTrigger -Once `
                        -At (Get-Date).AddMinutes($spec.first_delay_minutes) `
                        -RepetitionInterval (New-TimeSpan -Hours $spec.interval_hours)
                } else {
                    $at = [datetime]::Today.Add([timespan]::Parse($spec.daily_at))
                    if ($at -le (Get-Date)) { $at = $at.AddDays(1) }
                    $trigger = New-ScheduledTaskTrigger -Daily -At $at
                }
                $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
                    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
                $principal = New-ScheduledTaskPrincipal -UserId $identity `
                    -LogonType Interactive -RunLevel Limited
                Register-ScheduledTask -TaskName $spec.name -TaskPath '\' `
                    -Description $spec.description -Action $action -Trigger $trigger `
                    -Settings $settings -Principal $principal -ErrorAction Stop | Out-Null
                $created += $spec.name
            }
        } catch {
            foreach ($name in $created) {
                Unregister-ScheduledTask -TaskName $name -TaskPath '\' `
                    -Confirm:$false -ErrorAction Stop
            }
            throw
        }
    } elseif ($config.action -eq 'remove') {
        if (@($rows | Where-Object { $_.installed -and -not $_.definition_matches }).Count) {
            throw 'refusing_unowned_task_removal'
        }
        if (@($existing | Where-Object State -eq 'Running').Count) {
            throw 'refusing_running_task_removal'
        }
        foreach ($task in $existing) {
            Unregister-ScheduledTask -TaskName $task.TaskName -TaskPath '\' `
                -Confirm:$false -ErrorAction Stop
        }
    }
    [pscustomobject]@{
        contract = 'solo-empire.windows-scraping-status.v1'
        action = $config.action; status = 'ok'; tasks = @($rows)
    } | ConvertTo-Json -Depth 8 -Compress
} catch {
    [pscustomobject]@{status = 'error'; error = $_.Exception.GetType().Name} |
        ConvertTo-Json -Compress
    exit 1
}
"""


def build_plan(lake: Path = DEFAULT_LAKE) -> dict[str, Any]:
    lake = lake.resolve()
    tasks = []
    intervals = {"news": 2, "crypto": 4, "fx": 6, "monitor": 1}
    daily = {"stocks": "08:00", "defi": "07:00", "seo": "08:30"}
    for index, job in enumerate(JOBS):
        command = [
            "-X", "utf8", str(Path(__file__).resolve()), "run",
            "--product", job, "--lake-uri", str(lake),
        ]
        tasks.append({
            "job": job, "name": "SoloEmpire-Scraping-" + job,
            "description": MARKER + ";job=" + job,
            "execute": sys.executable,
            "arguments": subprocess.list2cmdline(command),
            "working_directory": str(ROOT),
            "interval_hours": intervals.get(job, 0),
            "daily_at": daily.get(job),
            "first_delay_minutes": 15 + index * 5,
        })
    return {
        "contract": "solo-empire.windows-scraping-plan.v1",
        "status": "plan-not-installed",
        "tasks": tasks,
        "run_context": "current signed-in user; limited privileges; no passwords",
        "overlap_policy": "IgnoreNew plus source and log locks",
        "execution_limit_minutes": 15,
        "log_retention": {"directory": str(LOG_DIR), "max_bytes": 2_000_000, "backups": 3},
        "external_delivery": "disabled",
        "approval_required": ["host", "identity", "log_retention", "rollback"],
        "excluded": ["jobs", "discovery", "draft-source-products"],
    }


def require_permission(product: str) -> None:
    if product == "monitor":
        return
    import yaml

    config = yaml.safe_load(
        (ROOT / "systems" / "ai-data" / "scraping-data-coverage.yaml").read_text(encoding="utf-8")
    )
    rows = [row for row in config["products"] if row.get("id") == product]
    if len(rows) != 1 or rows[0].get("permission", {}).get("status") not in {"approved", "bounded"}:
        raise ValueError("source_permission_required")


def _is_windows() -> bool:
    """Host predicate kept separate so tests can simulate Windows safely."""
    return os.name == "nt"


def manage(action: str, lake: Path, *, approved: bool = False) -> dict[str, Any]:
    if action not in {"status", "install", "remove"}:
        raise ValueError("unsupported_scheduler_action")
    if action != "status" and not approved:
        raise ValueError("host_approval_required")
    if not _is_windows():
        raise ValueError("windows_host_required")
    lake = lake.resolve()
    if action == "install":
        if not lake.is_dir() or not os.access(lake, os.W_OK):
            raise ValueError("existing_writable_local_lake_required")
        import bs4
        import duckdb
        import feedparser
        import httpx
        import pyarrow

        for job in JOBS:
            require_permission(job)
        from data_lake.scraping_coverage import _read_crontab

        crontab, _ = _read_crontab()
        tags = (
            "book-news-scraping-feeds", "book-crypto-data-feeds", "book-stock-data-feeds",
            "book-fx-data-feeds", "book-defi-data-feeds", "book-seo-data-feeds",
        )
        if any(tag in crontab for tag in tags):
            raise ValueError("existing_posix_scheduler_requires_operator_cutover")
    config = build_plan(lake)
    config.update(action=action, operator_approved=approved)
    encoded = base64.b64encode(POWERSHELL.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        input=json.dumps(config), capture_output=True, text=True, encoding="utf-8",
        timeout=60, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode:
        raise ValueError("windows_scheduler_operation_failed")
    result = json.loads(completed.stdout)
    if (
        not isinstance(result, dict)
        or result.get("contract") != "solo-empire.windows-scraping-status.v1"
        or result.get("action") != action
        or result.get("status") != "ok"
        or not isinstance(result.get("tasks"), list)
        or len(result["tasks"]) != len(JOBS)
        or any(not isinstance(row, dict) for row in result["tasks"])
        or any(not isinstance(row.get("job"), str) for row in result["tasks"])
        or {row["job"] for row in result["tasks"]} != set(JOBS)
        or any(
            row.get("task_name") != "SoloEmpire-Scraping-" + row["job"]
            or any(type(row.get(key)) is not bool for key in ("installed", "enabled", "definition_matches"))
            for row in result["tasks"]
        )
    ):
        raise ValueError("invalid_windows_scheduler_result")
    return result


def run_cycle(product: str, lake: Path) -> dict[str, Any]:
    require_permission(product)
    if product == "monitor":
        from data_lake.run_collection_monitor import DEFAULT_OUTPUT, run_monitor

        return run_monitor(DEFAULT_OUTPUT, probe_api=True)
    if not lake.is_dir() or not os.access(lake, os.W_OK):
        raise ValueError("existing_writable_local_lake_required")
    if product == "news":
        from data_lake.run_news_capture import run_news_cycle

        return run_news_cycle(lake_uri=str(lake), limit=50, attempts=2)
    if product == "seo":
        from data_lake.run_seo_capture import run_seo_cycle

        return run_seo_cycle(lake_uri=str(lake), attempts=2, timeout_seconds=180)
    from data_lake.run_market_capture import run_market_cycle, select_products

    return run_market_cycle(
        lake_uri=str(lake), products=select_products([product]), attempts=2,
        timeout_seconds=180, lock_timeout_seconds=30,
    )


def run_logged(product: str, lake: Path) -> tuple[dict[str, Any], int]:
    if product not in JOBS:
        raise ValueError("unsupported_scheduled_product")
    with acquire_lock(LOG_DIR / (product + ".lock")):
        logger = logging.getLogger("scraping.windows." + product)
        handler = RotatingFileHandler(
            LOG_DIR / (product + ".log"), maxBytes=2_000_000, backupCount=3, encoding="utf-8",
        )
        formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s")
        formatter.converter = gmtime
        handler.setFormatter(formatter)
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            logger.info("cycle_started product=%s", product)
            try:
                report = run_cycle(product, lake.resolve())
                status = report.get("status")
                if status not in {"ok", "attention", "failed", "error", "locked"}:
                    raise ValueError("invalid_capture_cycle_status")
                result = {"product": product, "status": status}
                code = 0 if status == "ok" or (product == "monitor" and status == "attention") else (
                    2 if status == "locked" else 1
                )
            except (OSError, ValueError, RuntimeError, ImportError) as exc:
                result = {"product": product, "status": "error", "error": type(exc).__name__}
                code = 1
            logger.info("cycle_result %s exit_code=%s", json.dumps(result), code)
            return result, code
        finally:
            logger.removeHandler(handler)
            handler.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "status", "install", "remove", "run"], nargs="?", default="plan")
    parser.add_argument("--lake-uri", type=Path, default=DEFAULT_LAKE)
    parser.add_argument(
        "--host-approved", action="store_true",
        help="Operator approved host, current-user identity, log retention and rollback",
    )
    parser.add_argument("--product", choices=JOBS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "plan":
            result, code = build_plan(args.lake_uri), 0
        elif args.action == "run":
            if args.product is None:
                parser.error("run requires --product")
            if args.dry_run:
                result, code = {
                    "status": "dry-run", "product": args.product,
                    "network": "not-used", "writes": "not-used",
                }, 0
            else:
                result, code = run_logged(args.product, args.lake_uri)
        else:
            if args.dry_run:
                raise ValueError("dry_run_requires_run_action")
            result = manage(args.action, args.lake_uri, approved=args.host_approved)
            if args.action == "install":
                result = manage("status", args.lake_uri)
                if len(result["tasks"]) != len(JOBS) or any(
                    row.get("installed") is not True or row.get("enabled") is not True
                    or row.get("definition_matches") is not True for row in result["tasks"]
                ):
                    raise ValueError("installed_scheduler_verification_failed")
            elif args.action == "remove":
                result = manage("status", args.lake_uri)
                if any(row["installed"] for row in result["tasks"]):
                    raise ValueError("removed_scheduler_verification_failed")
            code = 0
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.SubprocessError) as exc:
        safe_error = str(exc) if isinstance(exc, (ValueError, LockBusyError)) else type(exc).__name__
        print(json.dumps({"status": "error", "error": safe_error}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
