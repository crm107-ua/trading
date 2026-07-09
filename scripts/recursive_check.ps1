# Recursive analysis — estabilidad de indicadores vs warmup (Windows).
param(
    [string]$Strategy = "SmokeTestStrategy",
    [string]$Timerange = "20240101-20240320",
    [string]$StartupCandles = "199 499 999 1999"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> Recursive analysis: $Strategy ($Timerange)"

docker compose run --rm freqtrade recursive-analysis `
  --config user_data/config/base.json `
  --config user_data/config/backtest.json `
  --strategy $Strategy `
  --strategy-path user_data/strategies `
  --timerange $Timerange `
  --startup-candle $StartupCandles

Write-Host "==> Revisar tabla: variación <0.1% en columna del startup_candle_count de la estrategia."
