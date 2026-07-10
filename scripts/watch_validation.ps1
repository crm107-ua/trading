# Vigilante de validación — progreso Y muerte del run (ruidoso, no silencioso).
#
# Uso:
#   pwsh scripts/watch_validation.ps1 -Strategy MeanRevBB -Seeds 3 -Epochs 300
#
# Atasco:
#   semillas — StaleCycles × IntervalSec (default 4×300s ≈ 20 min sin líneas nuevas)
#   WF       — StaleHoursWf sin progreso (default 5.5 h; líneas nuevas o .fthypt nuevo)
#
# Modo ruidoso: lock OFF o PID muerto sin report.json → beep + .run_failed.flag
param(
  [string]$Strategy = "MeanRevBB",
  [int]$Epochs = 300,
  [int]$Seeds = 3,
  [int]$IntervalSec = 300,
  [int]$StaleCycles = 4,
  [double]$StaleHoursWf = 5.5,
  [string]$FlagFile = "user_data/validation_reports/.run_failed.flag"
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$lastCount = -1
$lastFthyptPath = $null
$lastProgressTime = Get-Date
$monitoredRunId = $null
$seenLocked = $false

function Write-Alert([string]$Message) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $line = "[$ts] ALERTA: $Message"
  Write-Host $line -ForegroundColor Red
  $line | Out-File -FilePath $FlagFile -Encoding utf8 -Append
  try {
    [console]::beep(880, 400)
    Start-Sleep -Milliseconds 150
    [console]::beep(660, 400)
    Start-Sleep -Milliseconds 150
    [console]::beep(880, 400)
  } catch {}
}

function Test-ReportExists([string]$StrategyName, [string]$RunId) {
  if (-not $RunId) { return $false }
  $path = "user_data/validation_reports/$StrategyName/$RunId/report.json"
  return Test-Path $path
}

function Get-RunHyperoptContext([string]$StrategyName, [int]$SeedTotal) {
  $ctx = @{
    phaseLabel = ""
    archNum = 0
    archTotal = $SeedTotal
    runId = ""
  }
  $lockPath = "user_data/validation_reports/.run_lock.json"
  if (-not (Test-Path $lockPath)) { return $ctx }

  $lock = Get-Content $lockPath -Raw | ConvertFrom-Json
  if ($lock.strategy -ne $StrategyName) { return $ctx }
  $ctx.runId = [string]$lock.run_id

  $completed = 0
  $ckPath = "user_data/validation_reports/$StrategyName/$($lock.run_id)/checkpoint.json"
  if (Test-Path $ckPath) {
    $ck = Get-Content $ckPath -Raw | ConvertFrom-Json
    if ($ck.completed_seeds) { $completed = @($ck.completed_seeds).Count }
  }

  if ($completed -ge $SeedTotal) {
    $ctx.phaseLabel = "WF"
    return $ctx
  }

  $archNum = $completed + 1
  $ctx.archNum = $archNum
  $ctx.phaseLabel = "semilla $archNum/$SeedTotal  arch $archNum/$SeedTotal"
  return $ctx
}

Write-Host "Vigilante: $Strategy cada ${IntervalSec}s"
Write-Host "  semillas: atasco tras $($StaleCycles * $IntervalSec)s sin progreso"
Write-Host "  WF:       atasco tras ${StaleHoursWf}h sin progreso (lineas o .fthypt nuevo)"
Write-Host "Bandera de fallo: $FlagFile"

while ($true) {
  $lockOut = python -m pipeline.run_lock check 2>&1 | Out-String
  $runCtx = Get-RunHyperoptContext -StrategyName $Strategy -SeedTotal $Seeds
  $isWf = ($runCtx.phaseLabel -eq "WF")
  $staleThresholdSec = if ($isWf) { $StaleHoursWf * 3600.0 } else { $StaleCycles * $IntervalSec }

  if ($lockOut -match "LOCKED") {
    $seenLocked = $true
    if ($runCtx.runId) { $monitoredRunId = $runCtx.runId }

    $pidMatch = [regex]::Match($lockOut, "pid=(\d+)")
    $lockPid = if ($pidMatch.Success) { [int]$pidMatch.Groups[1].Value } else { 0 }
    $proc = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
    if (-not $proc) {
      $rid = if ($monitoredRunId) { $monitoredRunId } else { "?" }
      if (-not (Test-ReportExists -StrategyName $Strategy -RunId $rid)) {
        Write-Alert "Lock LOCKED pero PID $lockPid no existe — run muerto sin report.json (run_id=$rid)."
      }
    }
  } elseif ($lockOut -match "OK:") {
    if ($seenLocked -and $monitoredRunId) {
      if (-not (Test-ReportExists -StrategyName $Strategy -RunId $monitoredRunId)) {
        Write-Alert "Lock liberado inesperadamente sin report.json (run_id=$monitoredRunId). Revisar terminal del orquestador."
      }
      $seenLocked = $false
    }
  }

  $f = Get-ChildItem "user_data/hyperopt_results/strategy_${Strategy}_*.fthypt" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

  if ($f) {
    $n = (Get-Content $f.FullName | Measure-Object -Line).Lines
    $pct = [math]::Round(100 * $n / $Epochs, 1)
    $phase = if ($runCtx.phaseLabel) { "  $($runCtx.phaseLabel)" } else { "" }
    $lockState = if ($lockOut -match "LOCKED") { "ON" } else { "OFF" }
    Write-Host "$(Get-Date -Format HH:mm:ss)$phase  $($f.Name)  epoch $n/$Epochs ($pct%)  lock=$lockState"

    $newFile = ($f.FullName -ne $lastFthyptPath)
    $newLines = ($n -gt $lastCount)
    if ($newFile -or $newLines) {
      $lastProgressTime = Get-Date
      $lastCount = $n
      $lastFthyptPath = $f.FullName
    } elseif ($lockOut -match "LOCKED") {
      $idleSec = ((Get-Date) - $lastProgressTime).TotalSeconds
      if ($idleSec -ge $staleThresholdSec) {
        $phaseName = if ($isWf) { "WF" } else { "semillas" }
        $idleH = [math]::Round($idleSec / 3600.0, 1)
        Write-Alert "Atasco $phaseName`: sin progreso hyperopt durante ${idleH}h (conteo=$n, archivo=$($f.Name)). Mirar logs Docker/orquestador."
        $lastProgressTime = Get-Date
      }
    }
  } else {
    Write-Host "$(Get-Date -Format HH:mm:ss)  (sin .fthypt para $Strategy)  lock=$(if ($lockOut -match 'LOCKED') {'ON'} else {'OFF'})"
    if ($lockOut -match "LOCKED" -and $isWf) {
      $idleSec = ((Get-Date) - $lastProgressTime).TotalSeconds
      if ($idleSec -ge $staleThresholdSec) {
        Write-Alert "Atasco WF: lock ON pero sin .fthypt para $Strategy durante $([math]::Round($idleSec / 3600.0, 1))h. Mirar logs."
        $lastProgressTime = Get-Date
      }
    }
  }

  Start-Sleep -Seconds $IntervalSec
}
