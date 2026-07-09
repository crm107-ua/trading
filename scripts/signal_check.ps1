# Signal truncation check (Windows).
param(
    [string]$Strategy = "SmokeTestStrategy",
    [string]$Timerange = "20240101-20240320"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

docker compose run --rm freqtrade python user_data/tools/signal_truncation_check.py `
  --strategy $Strategy `
  --timerange $Timerange
