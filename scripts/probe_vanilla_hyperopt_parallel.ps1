# Control vainilla: SampleStrategy + config mínimo, hyperopt -j 2, sin montar hyperopt_results del host.
# Respeta lock de validación (aborta si hay run activo).
# Uso: .\scripts\probe_vanilla_hyperopt_parallel.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$Root = (Get-Location).Path -replace '\\', '/'

Write-Host "==> Comprobar lock de validación"
python -m pipeline.run_lock check
if ($LASTEXITCODE -eq 3) {
  Write-Host "ABORT: hay validación activa. Espere o use probe tras el run."
  exit 3
}

$Image = "freqtradeorg/freqtrade@sha256:87aa5c6d65359b34e9d99a0bb260a38c0efe0315253811e6f48c2afe8f278a6a"

Write-Host "==> Pickle check vainilla (aislado)"
docker run --rm `
  -v "$Root/user_data/fixtures:/freqtrade/user_data/fixtures:ro" `
  -v "$Root/user_data/data:/freqtrade/user_data/data:ro" `
  -v "$Root/user_data/tools:/freqtrade/user_data/tools:ro" `
  -v "$Root/pipeline:/freqtrade/pipeline:ro" `
  -v "$Root/user_data/validation_reports:/freqtrade/user_data/validation_reports:ro" `
  --entrypoint python `
  $Image `
  user_data/tools/hyperopt_pickle_check.py --vanilla --inspect

$pickleExit = $LASTEXITCODE

Write-Host ""
Write-Host "==> Hyperopt real SampleStrategy -j 2 epochs 2 (hyperopt_results efímero en contenedor)"
docker run --rm `
  -v "$Root/user_data/fixtures:/freqtrade/user_data/fixtures:ro" `
  -v "$Root/user_data/data:/freqtrade/user_data/data:ro" `
  $Image `
  hyperopt `
  --config user_data/fixtures/vanilla_hyperopt.json `
  --strategy SampleStrategy `
  --strategy-path freqtrade/templates `
  --timerange 20240101-20240201 `
  -i 1h `
  --spaces buy sell roi stoploss `
  --epochs 2 `
  --random-state 42 `
  --min-trades 5 `
  --hyperopt-loss SharpeHyperOptLoss `
  -j 2

$hyperExit = $LASTEXITCODE
Write-Host ""
Write-Host "pickle_check exit=$pickleExit  hyperopt_j2 exit=$hyperExit"
if ($hyperExit -eq 0) {
  Write-Host "RESULT: control vainilla hyperopt -j 2 OK. Si el lab falla, culpable = config/user_data (no entorno ni Py 3.14)."
} else {
  Write-Host "RESULT: control vainilla hyperopt -j 2 FALLA — investigar entorno Docker Desktop/joblib."
}
exit $hyperExit
