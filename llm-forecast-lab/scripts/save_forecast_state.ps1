# Guarda checkpoint del forecast antes de apagar el PC.
# Estado real: data/lab.sqlite + data/responses/ (cache LLM).
# Uso: .\scripts\save_forecast_state.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$env:NODE_OPTIONS = "--max-old-space-size=16384"

Write-Host "Guardando checkpoint forecast..."
node dist/cli.js forecast-status --pipeline naive --model meta/llama-3.3-70b-instruct

Write-Host ""
Write-Host "Listo. Archivos criticos (no borrar):"
Write-Host "  data\lab.sqlite"
Write-Host "  data\responses\"
Write-Host "  output\forecast_state.json"
Write-Host ""
Write-Host "Tras reiniciar: .\scripts\resume_forecast.ps1"
