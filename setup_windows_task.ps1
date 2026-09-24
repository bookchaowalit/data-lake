param(
    [ValidateSet('plan', 'install', 'status', 'remove')]
    [string]$Action = 'plan'
)

$ErrorActionPreference = 'Stop'
$TaskName = 'SoloEmpire-Opportunity-Discovery'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$Runner = Join-Path $PSScriptRoot 'run_scheduled_acquisition.py'
$WindowsRunner = Join-Path $PSScriptRoot 'run_windows_acquisition.ps1'
$PowerShell = (Get-Command 'powershell.exe' -ErrorAction Stop).Source
$LogFile = Join-Path $Root 'data\logs\discovery-portfolio-scheduled.log'

function Get-DiscoveryPython {
    $command = Get-Command 'python.exe' -ErrorAction Stop
    $python = $command.Source
    & $python -X utf8 -c "import sys, pyarrow; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'The selected Python runtime must be Python 3.10+ and include PyArrow.'
    }
    return $python
}

function Show-Plan {
    Write-Output 'Discovery Windows task plan (not installed)'
    Write-Output "Task: $TaskName"
    Write-Output 'Schedule: every 6 hours; first run is 6 hours after installation'
    Write-Output 'Run context: current signed-in user, limited privileges'
    Write-Output 'Overlap policy: ignore a new run while a prior run is active'
    Write-Output 'Window policy: hidden background process'
    Write-Output "Local summary log: $LogFile (rotates at 2 MB; retains 3 backups)"
    Write-Output "Install: powershell.exe -NoProfile -File `"$PSCommandPath`" install"
    Write-Output "Remove: powershell.exe -NoProfile -File `"$PSCommandPath`" remove"
}

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Output "Status: NOT INSTALLED ($TaskName)"
        return
    }

    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Output "Status: $($task.State)"
    Write-Output "Task: $TaskName"
    Write-Output "Run as: $($task.Principal.UserId) ($($task.Principal.LogonType))"
    Write-Output "Next run: $($info.NextRunTime)"
    if ($info.LastTaskResult -eq 267011) {
        Write-Output 'Last run: not yet run'
    }
    else {
        Write-Output "Last run: $($info.LastRunTime)"
    }
    Write-Output "Last result: $($info.LastTaskResult)"
    Write-Output "Log: $LogFile"
}

function Install-Task {
    if (-not (Test-Path -LiteralPath $Runner -PathType Leaf) -or -not (Test-Path -LiteralPath $WindowsRunner -PathType Leaf)) {
        throw 'A scheduled acquisition runner file is missing.'
    }
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        throw "Task already exists. Run '$PSCommandPath status' or '$PSCommandPath remove' first."
    }

    $python = Get-DiscoveryPython
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $action = New-ScheduledTaskAction `
        -Execute $PowerShell `
        -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$WindowsRunner`" -PythonPath `"$python`"" `
        -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger `
        -Once `
        -At (Get-Date).AddHours(6) `
        -RepetitionInterval (New-TimeSpan -Hours 6)
    $settings = New-ScheduledTaskSettingsSet `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 3)
    $principal = New-ScheduledTaskPrincipal `
        -UserId $identity.Name `
        -LogonType Interactive `
        -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description 'Refreshes the local Opportunity Discovery pilots every six hours.' `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal | Out-Null

    Write-Output "Installed user-level task: $TaskName"
    Write-Output 'The first run is scheduled six hours from now.'
    Show-Status
}

function Remove-Task {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Output "Status: NOT INSTALLED ($TaskName)"
        return
    }

    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed task: $TaskName"
}

switch ($Action) {
    'plan' { Show-Plan }
    'install' { Install-Task }
    'status' { Show-Status }
    'remove' { Remove-Task }
}
