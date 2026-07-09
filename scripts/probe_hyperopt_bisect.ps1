# Celdas B y C de la matriz 2x2 (post-MeanRevBB).
# Guarda traceback completo por celda en user_data/validation_reports/hyperopt_bisect/.
#
# Uso:
#   .\scripts\probe_hyperopt_bisect.ps1 -Cell lab-sample
#   .\scripts\probe_hyperopt_bisect.ps1 -Cell meanrev-vanilla
#   .\scripts\probe_hyperopt_bisect.ps1 -Cell all

param(
  [ValidateSet("lab-sample", "meanrev-vanilla", "all")]
  [string]$Cell = "all"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$Root = (Get-Location).Path -replace '\\', '/'
$Image = "freqtradeorg/freqtrade@sha256:87aa5c6d65359b34e9d99a0bb260a38c0efe0315253811e6f48c2afe8f278a6a"
$LogDir = "user_data/validation_reports/hyperopt_bisect"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

python -m pipeline.run_lock check
if ($LASTEXITCODE -eq 3) {
  Write-Host "ABORT: validación activa."
  exit 3
}

function Invoke-HyperoptProbe {
  param(
    [string]$CellId,
    [string]$Name,
    [string[]]$Args
  )
  $logFile = Join-Path $LogDir "cell_${CellId}_${Stamp}.log"
  Write-Host ""
  Write-Host "==> $Name"
  Write-Host "    log: $logFile"

  $output = & docker run --rm @Args 2>&1
  $output | Out-File -FilePath $logFile -Encoding utf8
  $output | Select-Object -Last 15

  $code = $LASTEXITCODE
  $status = if ($code -eq 0) { "PASS" } else { "FAIL" }
  Add-Content -Path $logFile -Value "`n=== RESULT: $status exit=$code ==="

  Write-Host "RESULT $Name : $status (exit $code)"
  return @{ Exit = $code; Log = $logFile; Status = $status }
}

$commonTail = @(
  "--epochs", "2",
  "--random-state", "42",
  "--min-trades", "5",
  "-j", "2",
  "--timerange", "20240101-20240201"
)

$results = @{}

if ($Cell -eq "all" -or $Cell -eq "lab-sample") {
  $argsB = @(
    "-v", "$Root/user_data/data:/freqtrade/user_data/data:ro",
    "-v", "$Root/user_data/config:/freqtrade/user_data/config:ro",
    $Image, "hyperopt",
    "--config", "user_data/config/base.json",
    "--config", "user_data/config/backtest.json",
    "--strategy", "SampleStrategy",
    "--strategy-path", "freqtrade/templates",
    "-i", "1h",
    "--spaces", "buy", "sell", "roi", "stoploss",
    "--hyperopt-loss", "SharpeHyperOptLoss"
  ) + $commonTail
  $results["lab-sample"] = Invoke-HyperoptProbe "B" "B: SampleStrategy + config lab" $argsB
}

if ($Cell -eq "all" -or $Cell -eq "meanrev-vanilla") {
  $argsC = @(
    "-v", "$Root/user_data/data:/freqtrade/user_data/data:ro",
    "-v", "$Root/user_data/fixtures:/freqtrade/user_data/fixtures:ro",
    "-v", "$Root/user_data/strategies:/freqtrade/user_data/strategies:ro",
    "-v", "$Root/user_data/hyperopts:/freqtrade/user_data/hyperopts:ro",
    $Image, "hyperopt",
    "--config", "user_data/fixtures/vanilla_hyperopt.json",
    "--hyperopt-path", "user_data/hyperopts",
    "--strategy", "MeanRevBB",
    "--strategy-path", "user_data/strategies",
    "-i", "1h",
    "--spaces", "buy", "sell",
    "--hyperopt-loss", "QuantRobustLoss"
  ) + $commonTail
  $results["meanrev-vanilla"] = Invoke-HyperoptProbe "C" "C: MeanRevBB + config vainilla" $argsC
}

$summaryFile = Join-Path $LogDir "summary_${Stamp}.txt"
$lines = @(
  "hyperopt bisect $Stamp",
  "known: A=vainilla+SampleStrategy PASS, D=lab+MeanRevBB FAIL",
  ""
)
foreach ($k in $results.Keys) {
  $r = $results[$k]
  $lines += "$k = $($r.Status) exit=$($r.Exit) log=$($r.Log)"
}
$lines += ""
$lines += "Compare tracebacks C vs D: same PicklingError object => single cause; different => stacked causes."
$lines | Out-File -FilePath $summaryFile -Encoding utf8

Write-Host ""
Write-Host "Resumen: $summaryFile"
Write-Host "Matriz conocida: A=PASS, D=FAIL — comparar tracebacks en $LogDir"
Write-Host "Interpretación: docs/HYPEROPT_PARALLEL_BISECT.md"

if ($results.Count -eq 0) { exit 0 }
$worst = ($results.Values | ForEach-Object { $_.Exit } | Measure-Object -Maximum).Maximum
exit $worst
