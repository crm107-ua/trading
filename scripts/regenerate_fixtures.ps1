# Regenera fixtures sintéticos (BULL + RANGE) vía Docker — requiere TA-Lib.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> Regenerando fixtures (BULL + RANGE)"
docker compose run --rm --entrypoint python `
  -v "${Root}:/work" `
  -w /work `
  freqtrade tests/fixtures/generate_data.py

Write-Host "==> Fixtures en tests/fixtures/data/binance/"
docker compose run --rm --entrypoint "python" -v "${Root}:/work" -w /work freqtrade tests/fixtures/generate_data.py