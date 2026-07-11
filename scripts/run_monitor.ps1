# Wrapper para tarea programada — monitor dry-run XSec (reinicio automatico via Task Scheduler).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$LogDir = Join-Path $Root "user_data\logs"
if (-not (Test-Path $LogDir)) {
  New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$LogFile = Join-Path $LogDir "dryrun_monitor_task.log"
$Stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogFile -Value "[$Stamp] monitor task started (pid=$PID)"

python -m risk.monitor --interval 300 2>&1 | ForEach-Object {
  Add-Content -Path $LogFile -Value $_
}

$Stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogFile -Value "[$Stamp] monitor exited code=$LASTEXITCODE"

exit $LASTEXITCODE
