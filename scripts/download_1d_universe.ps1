# Descarga 1d del universo RelativeMomentum — SIN --erase (no pisar datos existentes).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$pairs = @(
  "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"
) -join " "

Write-Host "==> Descarga 1d (append) para universo RelativeMomentum"
docker compose run --rm --no-deps freqtrade download-data `
  --config user_data/config/base.json `
  --config user_data/config/backtest.json `
  --exchange binance `
  --timeframes 1d `
  --pairs $pairs `
  --timerange 20210101-

Write-Host "Verificar: Get-ChildItem user_data/data/binance/*-1d.feather"
