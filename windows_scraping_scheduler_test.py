#!/usr/bin/env python3
"""Offline native scheduler gates, bounded runners and Windows cmdlet contracts."""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra" / "scripts"))

from data_lake import scraping_coverage as coverage
from data_lake import windows_scraping_scheduler as scheduler


class WindowsSchedulerTests(unittest.TestCase):
    def test_plan_is_explicit_bounded_and_does_not_probe_or_write(self) -> None:
        with patch.object(scheduler, "manage", side_effect=AssertionError("scheduler accessed")):
            with patch.object(Path, "mkdir", side_effect=AssertionError("file write")):
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(scheduler.main(["plan"]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["status"], "plan-not-installed")
        self.assertEqual({row["job"] for row in plan["tasks"]}, set(scheduler.JOBS))
        self.assertNotIn("jobs", scheduler.JOBS)
        self.assertNotIn("discovery", scheduler.JOBS)
        self.assertEqual(plan["external_delivery"], "disabled")
        self.assertEqual(plan["log_retention"]["max_bytes"], 2_000_000)
        self.assertEqual(plan["log_retention"]["backups"], 3)
        rows = {row["job"]: row for row in plan["tasks"]}
        self.assertEqual(rows["news"]["interval_hours"], 2)
        self.assertEqual(rows["crypto"]["interval_hours"], 4)
        self.assertEqual(rows["fx"]["interval_hours"], 6)
        self.assertEqual(rows["monitor"]["interval_hours"], 1)
        self.assertEqual(rows["stocks"]["daily_at"], "08:00")
        self.assertEqual(rows["defi"]["daily_at"], "07:00")
        self.assertEqual(rows["seo"]["daily_at"], "08:30")

    def test_install_and_remove_require_approval_before_any_subprocess(self) -> None:
        with patch.object(scheduler.subprocess, "run") as run:
            for action in ("install", "remove"):
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(scheduler.main([action]), 1)
                self.assertIn("host_approval_required", output.getvalue())
            run.assert_not_called()

    def test_dry_runs_never_import_collectors_or_write_even_for_monitor(self) -> None:
        with patch.object(scheduler, "run_logged", side_effect=AssertionError("live capture")):
            with patch.object(Path, "mkdir", side_effect=AssertionError("file write")):
                for job in scheduler.JOBS:
                    with redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(scheduler.main(["run", "--product", job, "--dry-run"]), 0)
                    self.assertEqual(json.loads(output.getvalue())["writes"], "not-used")

    def test_remove_reports_only_verified_post_removal_state(self) -> None:
        absent = {"status": "ok", "tasks": [{"installed": False} for _ in scheduler.JOBS]}
        present = {"status": "ok", "tasks": [{"installed": True}]}
        for final, expected in ((absent, 0), (present, 1)):
            with patch.object(scheduler, "manage", side_effect=[present, final]) as manage:
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(scheduler.main(["remove", "--host-approved"]), expected)
            self.assertEqual(manage.call_args_list[-1].args[0], "status")
            if expected == 0:
                self.assertTrue(all(not row["installed"] for row in json.loads(output.getvalue())["tasks"]))
            else:
                self.assertIn("removed_scheduler_verification_failed", output.getvalue())

    def test_revoked_source_permission_prevents_capture(self) -> None:
        with patch.object(Path, "read_text", return_value="products:\n- id: news\n  permission:\n    status: draft\n"):
            with self.assertRaisesRegex(ValueError, "source_permission_required"):
                scheduler.run_cycle("news", scheduler.DEFAULT_LAKE)

    def test_wrapper_uses_existing_bounded_market_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(scheduler, "require_permission"):
                with patch("data_lake.run_market_capture.run_market_cycle", return_value={"status": "ok"}) as run:
                    scheduler.run_cycle("crypto", Path(directory))
        self.assertEqual([row.product for row in run.call_args.kwargs["products"]], ["crypto"])
        self.assertEqual(run.call_args.kwargs["attempts"], 2)
        self.assertEqual(run.call_args.kwargs["timeout_seconds"], 180)
        self.assertEqual(run.call_args.kwargs["lock_timeout_seconds"], 30)

    def test_monitor_never_requests_external_delivery(self) -> None:
        with patch("data_lake.run_collection_monitor.run_monitor", return_value={"status": "attention"}) as run:
            scheduler.run_cycle("monitor", scheduler.DEFAULT_LAKE)
        self.assertEqual(run.call_args.kwargs, {"probe_api": True})

    def test_logs_are_rotating_aggregate_only_and_failure_is_not_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            with patch.object(scheduler, "LOG_DIR", log_dir):
                with patch.object(scheduler, "run_cycle", return_value={
                    "status": "failed", "raw_rows": "PRIVATE", "provider_error": "PRIVATE",
                }):
                    result, code = scheduler.run_logged("news", scheduler.DEFAULT_LAKE)
                text = (log_dir / "news.log").read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertEqual(result, {"product": "news", "status": "failed"})
        self.assertNotIn("PRIVATE", text)
        self.assertIn("exit_code=1", text)
        self.assertIn("Z INFO", text)

    def test_logged_provider_errors_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(scheduler, "LOG_DIR", Path(directory)):
                with patch.object(scheduler, "run_cycle", side_effect=ValueError("PRIVATE PROVIDER PAYLOAD")):
                    result, code = scheduler.run_logged("news", scheduler.DEFAULT_LAKE)
                text = (Path(directory) / "news.log").read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertEqual(result["error"], "ValueError")
        self.assertNotIn("PRIVATE", text)

    def test_contending_wrapper_does_not_call_source_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with patch.object(scheduler, "LOG_DIR", path), patch.object(scheduler, "run_cycle") as run:
                with scheduler.acquire_lock(path / "news.lock"):
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(scheduler.main(["run", "--product", "news"]), 1)
                run.assert_not_called()

    def test_windows_coverage_rejects_disabled_unowned_or_partial_evidence(self) -> None:
        rows = [{
            "job": job, "task_name": "SoloEmpire-Scraping-" + job,
            "installed": True, "enabled": True, "definition_matches": True,
        } for job in scheduler.JOBS]
        rows[0]["enabled"] = False
        rows[1]["definition_matches"] = False
        with patch.object(coverage.os, "name", "nt"):
            with patch.object(scheduler, "manage", return_value={"tasks": rows}):
                jobs, state = coverage._read_windows_schedule(ROOT)
                self.assertEqual(state, "available")
                self.assertEqual(jobs, set(scheduler.JOBS) - {"news", "crypto"})
                rows.pop()
                self.assertEqual(coverage._read_windows_schedule(ROOT), (set(), "invalid"))

    def test_host_probe_errors_never_create_schedule_evidence(self) -> None:
        with patch.object(coverage.os, "name", "nt"):
            with patch.object(scheduler, "manage", side_effect=ValueError("fixture failure")):
                self.assertEqual(coverage._read_windows_schedule(ROOT), (set(), "unavailable"))

    def test_managed_status_rejects_duplicate_jobs_and_nonboolean_evidence(self) -> None:
        rows = [{
            "job": job, "task_name": "SoloEmpire-Scraping-" + job,
            "installed": False, "enabled": False, "definition_matches": False,
        } for job in scheduler.JOBS]
        for change in ("duplicate", "scalar", "unhashable"):
            payload = {
                "contract": "solo-empire.windows-scraping-status.v1",
                "action": "status", "status": "ok", "tasks": [dict(row) for row in rows],
            }
            if change == "duplicate":
                payload["tasks"][-1] = payload["tasks"][0]
            elif change == "scalar":
                payload["tasks"][0]["enabled"] = "false"
            else:
                payload["tasks"][0]["job"] = ["news"]
            completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
            with self.subTest(change=change), patch.object(scheduler, "_is_windows", return_value=True):
                with patch.object(scheduler.subprocess, "run", return_value=completed):
                    with self.assertRaisesRegex(ValueError, "invalid_windows_scheduler_result"):
                        scheduler.manage("status", scheduler.DEFAULT_LAKE)


MOCK_CMDLETS = r"""
$global:events = @()
function Save-Event($kind, $value) {
    [pscustomobject]@{kind=$kind;value=$value} | ConvertTo-Json -Depth 12 -Compress |
        Add-Content -LiteralPath $env:SCRAPING_TEST_EVENTS -Encoding UTF8
}
function Get-ScheduledTask {
    param($TaskPath, $ErrorAction)
    if ($env:SCRAPING_TEST_MODE -eq 'empty' -or $env:SCRAPING_TEST_MODE -eq 'rollback') { return }
    $plan = $env:SCRAPING_TEST_PLAN | ConvertFrom-Json
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    if ($env:SCRAPING_TEST_MODE -eq 'matching_account') {
        $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    }
    foreach ($spec in $plan.tasks) {
        $trigger = if ($spec.interval_hours) {
            [pscustomobject]@{
                Enabled=$true;CimClass=@{CimClassName='MSFT_TaskTimeTrigger'}
                Repetition=@{Interval="PT$($spec.interval_hours)H";Duration=$null}
            }
        } else {
            [pscustomobject]@{
                Enabled=$true;CimClass=@{CimClassName='MSFT_TaskDailyTrigger'}
                DaysInterval=1;StartBoundary="2026-10-01T$($spec.daily_at):00"
            }
        }
        $description = if ($env:SCRAPING_TEST_MODE -eq 'unowned') {'unowned'} else {$spec.description}
        [pscustomobject]@{
            TaskName=$spec.name;Description=$description
            State=$(if ($env:SCRAPING_TEST_MODE -eq 'running') {'Running'} else {'Ready'})
            Actions=@([pscustomobject]@{
                Execute=$spec.execute;Arguments=$spec.arguments;WorkingDirectory=$spec.working_directory
            })
            Triggers=@($trigger)
            Principal=@{UserId=$sid;LogonType='Interactive';RunLevel='Limited'}
            Settings=@{MultipleInstances='IgnoreNew';ExecutionTimeLimit='PT15M';Enabled=$true;StartWhenAvailable=$true}
        }
    }
}
function Get-ScheduledTaskInfo {
    param($InputObject, $ErrorAction)
    [pscustomobject]@{LastTaskResult=0;LastRunTime=(Get-Date);NextRunTime=(Get-Date).AddHours(1)}
}
function New-ScheduledTaskAction {
    param($Execute, $Argument, $WorkingDirectory)
    [pscustomobject]@{Execute=$Execute;Argument=$Argument;WorkingDirectory=$WorkingDirectory}
}
function New-ScheduledTaskTrigger {
    param([switch]$Once, [switch]$Daily, $At, $RepetitionInterval)
    [pscustomobject]@{Once=[bool]$Once;Daily=[bool]$Daily;At=$At;Interval=$RepetitionInterval.TotalHours}
}
function New-ScheduledTaskSettingsSet {
    param($MultipleInstances, [switch]$StartWhenAvailable, $ExecutionTimeLimit)
    [pscustomobject]@{MultipleInstances=$MultipleInstances;StartWhenAvailable=[bool]$StartWhenAvailable;Minutes=$ExecutionTimeLimit.TotalMinutes}
}
function New-ScheduledTaskPrincipal {
    param($UserId, $LogonType, $RunLevel)
    [pscustomobject]@{UserId=$UserId;LogonType=$LogonType;RunLevel=$RunLevel}
}
function Register-ScheduledTask {
    param($TaskName, $TaskPath, $Description, $Action, $Trigger, $Settings, $Principal, $ErrorAction)
    if ($env:SCRAPING_TEST_MODE -eq 'rollback' -and $TaskName -eq 'SoloEmpire-Scraping-stocks') {
        throw 'fixture registration failure'
    }
    Save-Event 'register' @{
        Name=$TaskName;Path=$TaskPath;Action=$Action;Trigger=$Trigger;Settings=$Settings;Principal=$Principal
    }
}
function Unregister-ScheduledTask {
    param($TaskName, $TaskPath, [switch]$Confirm, $ErrorAction)
    Save-Event 'unregister' @{Name=$TaskName;Path=$TaskPath}
}
"""


@unittest.skipUnless(os.name == "nt", "Windows cmdlet contract tests require Windows PowerShell")
class PowerShellSchedulerContractTests(unittest.TestCase):
    def execute(self, action: str, mode: str, *, approved: bool = True):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            config = scheduler.build_plan(Path(directory) / "lake with spaces")
            config.update(action=action, operator_approved=approved)
            script = MOCK_CMDLETS + scheduler.POWERSHELL
            run = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                 base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
                input=json.dumps(config), capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "SCRAPING_TEST_EVENTS": str(path),
                     "SCRAPING_TEST_MODE": mode, "SCRAPING_TEST_PLAN": json.dumps(config)},
                timeout=30, check=False,
            )
            events = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines()] if path.exists() else []
            return run, events

    def test_cmdlets_register_exactly_seven_current_user_limited_tasks(self) -> None:
        result, events = self.execute("install", "empty")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(events), 7)
        for event in events:
            self.assertEqual(event["kind"], "register")
            row = event["value"]
            self.assertEqual(row["Principal"]["LogonType"], "Interactive")
            self.assertEqual(row["Principal"]["RunLevel"], "Limited")
            self.assertEqual(row["Settings"]["Minutes"], 15)
            self.assertEqual(row["Settings"]["MultipleInstances"], "IgnoreNew")
            self.assertIn('"', row["Action"]["Argument"])
            self.assertIn("lake with spaces", row["Action"]["Argument"])

    def test_duplicate_names_are_never_replaced(self) -> None:
        result, events = self.execute("install", "matching")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, [])

    def test_partial_install_rolls_back_only_the_tasks_it_created(self) -> None:
        result, events = self.execute("install", "rollback")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([event["kind"] for event in events], ["register", "register", "unregister", "unregister"])
        self.assertEqual([event["value"]["Name"] for event in events], [
            "SoloEmpire-Scraping-news", "SoloEmpire-Scraping-crypto",
            "SoloEmpire-Scraping-news", "SoloEmpire-Scraping-crypto",
        ])

    def test_status_validates_live_definitions_without_mutations(self) -> None:
        for mode in ("matching", "matching_account"):
            with self.subTest(mode=mode):
                result, events = self.execute("status", mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertTrue(all(row["definition_matches"] for row in payload["tasks"]))
                self.assertEqual(events, [])

    def test_remove_refuses_unowned_or_running_tasks(self) -> None:
        for mode in ("unowned", "running"):
            with self.subTest(mode=mode):
                result, events = self.execute("remove", mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(events, [])

    def test_powershell_mutation_gate_is_independent_of_python_gate(self) -> None:
        result, events = self.execute("install", "empty", approved=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events, [])

    def test_remove_affects_only_exact_owned_tasks(self) -> None:
        result, events = self.execute("remove", "matching")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({event["value"]["Name"] for event in events}, {
            "SoloEmpire-Scraping-" + job for job in scheduler.JOBS
        })
        self.assertTrue(all(event["kind"] == "unregister" for event in events))


if __name__ == "__main__":
    unittest.main()
