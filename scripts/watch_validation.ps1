# Vigilante de validación — progreso Y muerte del run (ruidoso, no silencioso).
# Uso: pwsh scripts/watch_validation.ps1 [-Strategy MeanRevBB] [-IntervalSec 300] [-StaleCycles 4]
param(
  [string]$Strategy = "MeanRevBB",
  [int]$Epochs = 300,
  [int]$Seeds = 3,
  [int]$IntervalSec = 300,
  [int]$StaleCycles = 4,
  [string]$FlagFile = "user_data/validation_reports/.run_failed.flag"
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$lastCount = -1
$stale = 0

function Write-Alert([string]$Message) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $line = "[$ts] ALERTA: $Message"
  Write-Host $line -ForegroundColor Red
  $line | Out-File -FilePath $FlagFile -Encoding utf8 -Append
  try { [console]::beep(880, 400); Start-Sleep -Milliseconds 150; [console]::beep(660, 400) } catch {}
}

function Get-RunHyperoptContext([string]$StrategyName, [int]$SeedTotal) {
  $ctx = @{
    phaseLabel = ""
    archNum = 0
    archTotal = $SeedTotal
  }
  $lockPath = "user_data/validation_reports/.run_lock.json"
  if (-not (Test-Path $lockPath)) { return $ctx }

  $lock = Get-Content $lockPath -Raw | ConvertFrom-Json
  if ($lock.strategy -ne $StrategyName) { return $ctx }

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

Write-Host "Vigilante: $Strategy cada ${IntervalSec}s (stale tras $StaleCycles ciclos sin progreso)"
Write-Host "Bandera de fallo: $FlagFile"

while ($true) {
  $lockOut = python -m pipeline.run_lock check 2>&1 | Out-String

  if ($lockOut -match "LOCKED") {
    $pidMatch = [regex]::Match($lockOut, "pid=(\d+)")
    $lockPid = if ($pidMatch.Success) { [int]$pidMatch.Groups[1].Value } else { 0 }
    $proc = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
    if (-not $proc) {
      Write-Alert "Lock LOCKED pero PID $lockPid no existe — run muerto sin checkpoint."
    }
  } elseif ($lockOut -match "OK:") {
    if ($lastCount -gt 0) {
      Write-Alert "Lock liberado inesperadamente (sin report.json confirmado). Revisar terminal del orquestador."
    }
  }

  $f = Get-ChildItem "user_data/hyperopt_results/strategy_${Strategy}_*.fthypt" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

  $runCtx = Get-RunHyperoptContext -StrategyName $Strategy -SeedTotal $Seeds

  if ($f) {
    $n = (Get-Content $f.FullName | Measure-Object -Line).Lines
    $pct = [math]::Round(100 * $n / $Epochs, 1)
    $phase = if ($runCtx.phaseLabel) { "  $($runCtx.phaseLabel)" } else { "" }
    Write-Host "$(Get-Date -Format HH:mm:ss)$phase  $($f.Name)  epoch $n/$Epochs ($pct%)  lock=$(if ($lockOut -match 'LOCKED') {'ON'} else {'OFF'})"

    if ($n -eq $lastCount -and $lockOut -match "LOCKED") {
      $stale++
      if ($stale -ge $StaleCycles) {
        Write-Alert "Sin progreso en hyperopt durante $($StaleCycles * $IntervalSec)s (conteo=$n)."
        $stale = 0
      }
    } else {
      $stale = 0
      $lastCount = $n
    }
  } else {
    Write-Host "$(Get-Date -Format HH:mm:ss)  (sin .fthypt para $Strategy)"
  }

  Start-Sleep -Seconds $IntervalSec
}
