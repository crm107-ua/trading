# Descarga datos históricos vía Docker (Windows / PowerShell).
# Por defecto: descarga limpia (--erase). Usar PREPEND=1 solo para extender sin borrar.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Timerange = if ($env:TIMERANGE) { $env:TIMERANGE } else { "20210101-" }
$Timeframes = if ($env:TIMEFRAMES) { $env:TIMEFRAMES } else { "1h", "15m", "4h" }
$PairList = if ($env:PAIRS) { $env:PAIRS -split '\s+' } else { @(
  "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"
) }

Write-Host "==> Descargando datos Binance spot (user_data/data - solo reales)"
Write-Host "    Timerange: $Timerange"
Write-Host "    Pares: $($PairList -join ', ')"

$DownloadArgs = @(
  "compose", "run", "--rm", "freqtrade", "download-data",
  "--config", "user_data/config/base.json",
  "--config", "user_data/config/backtest.json",
  "--exchange", "binance",
  "--timerange", $Timerange,
  "--timeframes", $Timeframes,
  "--pairs", $PairList
)
if ($env:PREPEND -ne "1") {
  Write-Host "    Modo: --erase (descarga limpia)"
  $DownloadArgs += "--erase"
}

docker @DownloadArgs

Write-Host "==> Descarga completada en user_data/data/ (separado de tests/fixtures/data/)"
