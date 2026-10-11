param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPath
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$Runner = Join-Path $PSScriptRoot 'run_scheduled_acquisition.py'

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable is unavailable: $PythonPath"
}
if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) {
    throw "Scheduled acquisition runner is unavailable: $Runner"
}

$process = Start-Process `
    -FilePath $PythonPath `
    -ArgumentList "-X utf8 `"$Runner`"" `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -PassThru `
    -Wait
exit $process.ExitCode
