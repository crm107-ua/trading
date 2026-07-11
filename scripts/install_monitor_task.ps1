# Registra tarea programada Windows: monitor dry-run al inicio de sesion, reinicio si muere.
# Uso: .\scripts\install_monitor_task.ps1
# Requiere: dry-run en 8082; Python en PATH.

$ErrorActionPreference = "Stop"
$TaskName = "Trading-XSec-Dryrun-Monitor"
$ScriptPath = Join-Path $PSScriptRoot "run_monitor.ps1"

if (-not (Test-Path $ScriptPath)) {
  throw "No existe $ScriptPath"
}

$Action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$Settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero)

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $Action `
  -Trigger $Trigger `
  -Settings $Settings `
  -Principal $Principal `
  -Description "Monitor API dry-run XSecMomentum-m35 (puerto 8082), poll 5 min. Reinicia si el proceso muere." | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host "Tarea '$TaskName' registrada y arrancada."
Write-Host "  Script: $ScriptPath"
Write-Host "  Estado: user_data/dryrun_monitor_state.json"
Write-Host "  Log:    user_data/logs/dryrun_monitor_task.log"
Write-Host ""
Write-Host "Comprobar: Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
