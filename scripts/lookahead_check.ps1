# Lookahead analysis vía Docker (Windows).
param(
    [string]$Strategy = "SmokeTestStrategy",
    [string]$Timerange = "20240101-20240201"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> Lookahead analysis: $Strategy ($Timerange)"

docker compose run --rm freqtrade lookahead-analysis `
  --config user_data/config/base.json `
  --config user_data/config/backtest.json `
  --strategy $Strategy `
  --config user_data/config/lookahead.json `
  --strategy-path user_data/strategies `
  --timerange $Timerange
