# Pipeline de validación antes de backtest (Windows).
param(
  [string]$Strategy = "SmokeTestStrategy",
  [string]$Timerange = "",
  [string]$RecursiveRange = "",
  [string]$StartupCandles = "199 499 999 1999",
  [switch]$RealData
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$FixtureStrategies = @("SmokeTestStrategy", "TrendRider", "MeanRevBB", "BreakoutVol", "RegimeSwitcher", "GridDCA")
$ConfigArgs = @("user_data/config/base.json", "user_data/config/backtest.json")

if ($RealData) {
  if (-not $Timerange) { $Timerange = "20230101-20240320" }
  if (-not $RecursiveRange) { $RecursiveRange = "20230101-20240320" }
  Write-Host "==> Modo datos REALES (user_data/data)"
} else {
  if (-not $Timerange) { $Timerange = "20240101-20240320" }
  if (-not $RecursiveRange) { $RecursiveRange = "20240101-20240320" }
  if ($FixtureStrategies -contains $Strategy) {
    $ConfigArgs += "user_data/config/backtest_fixtures.json"
  }
  Write-Host "==> Modo FIXTURES (user_data/fixtures/data)"
}

$DockerConfigFlags = @()
$DockerDatadirFlags = @()
foreach ($cfg in $ConfigArgs) {
  $DockerConfigFlags += "--config"
  $DockerConfigFlags += $cfg
}
if (-not $RealData) {
  $DockerDatadirFlags += "--datadir"
  $DockerDatadirFlags += "/freqtrade/user_data/fixtures/data/binance"
}

$StartupCandleList = $StartupCandles -split '\s+'

Write-Host "==> Regime variety check: $Strategy ($Timerange)"
& docker compose run --rm --entrypoint python freqtrade user_data/tools/regime_variety_check.py --strategy $Strategy --timerange $Timerange @DockerConfigFlags
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Signal truncation check: $Strategy ($Timerange)"
& docker compose run --rm --entrypoint python freqtrade user_data/tools/signal_truncation_check.py --strategy $Strategy --timerange $Timerange @DockerConfigFlags
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Recursive analysis: $Strategy ($RecursiveRange)"
& docker compose run --rm freqtrade recursive-analysis @DockerConfigFlags @DockerDatadirFlags --strategy $Strategy --strategy-path user_data/strategies --timerange $RecursiveRange --startup-candle @StartupCandleList
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Lookahead trade-based (advisory): $Strategy ($Timerange)"
& docker compose run --rm freqtrade lookahead-analysis @DockerConfigFlags @DockerDatadirFlags --config user_data/config/lookahead.json --strategy $Strategy --strategy-path user_data/strategies --timerange $Timerange
Write-Host "    (advisory - ver docs/OPERATIONS.md)"

if ($Strategy -eq "GridDCA" -and -not $RealData) {
  Write-Host "==> GridDCA cycle check (fixtures)"
  & docker compose run --rm --entrypoint python freqtrade user_data/tools/grid_dca_check.py --strategy GridDCAFixture --timerange 20240120-20240128 --min-position-adjustments 3 --require-stop-after-dca --pairs BTC/USDT @DockerConfigFlags
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "==> Backtest: $Strategy ($Timerange)"
& docker compose run --rm freqtrade backtesting @DockerConfigFlags @DockerDatadirFlags --strategy $Strategy --timerange $Timerange --cache none --breakdown month
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Pipeline completado para $Strategy"
