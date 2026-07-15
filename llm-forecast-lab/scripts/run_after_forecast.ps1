# Day D — cuando el forecast termine (1471/1471):
#   .\scripts\run_after_forecast.ps1
#
# Orden de lectura: report.json → integrity → verdict → skill → CONCLUSIONS_SPACE → dos líneas.
# sim-paper / sim-grid NO forman parte del día D (post-verdict, pre-reg aparte).

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$env:NODE_OPTIONS = "--max-old-space-size=16384"

$total = node --input-type=module -e "import { openDb } from './dist/db.js'; console.log(openDb('live').prepare('select count(*) n from forecasts').get().n)"
$expected = 1471
if ([int]$total -lt $expected) {
  Write-Host "Forecast incompleto: $total / $expected. Espera a que termine o reanuda con:"
  Write-Host "  node dist/cli.js forecast --pipeline naive --mode live --model meta/llama-3.3-70b-instruct --provider nvidia"
  exit 1
}

Write-Host "Forecast completo ($total). Day D: score + report..."
node dist/cli.js eval-day-d --mode live --pipeline naive | Tee-Object -FilePath "output\eval_day_d.log"

Write-Host "Listo. Lee output\<runId>\report.json — integrity primero."
