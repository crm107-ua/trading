# Reanuda forecast 70B sin purgar filas existentes (resume por defecto).
# Uso: .\scripts\resume_forecast.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$env:NODE_OPTIONS = "--max-old-space-size=16384"

Write-Host "Estado actual:"
node dist/cli.js forecast-status --pipeline naive --model meta/llama-3.3-70b-instruct

Write-Host ""
Write-Host "Reanudando forecast (sin --fresh)..."
node dist/cli.js forecast `
  --pipeline naive `
  --mode live `
  --model meta/llama-3.3-70b-instruct `
  --provider nvidia 2>&1 | Tee-Object -FilePath "output\forecast_70b.log" -Append
