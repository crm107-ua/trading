# Probar hyperopt paralelo en imagen candidata Py 3.12 sin tocar hyperopt_results del host.
# Uso: .\scripts\probe_py312_hyperopt.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$Root = (Get-Location).Path -replace '\\', '/'

$Candidate = if ($env:FREQTRADE_IMAGE_PY312_CANDIDATE) { $env:FREQTRADE_IMAGE_PY312_CANDIDATE } else { "freqtradeorg/freqtrade:2025.3" }

Write-Host "==> Pull candidato: $Candidate"
docker pull $Candidate

Write-Host "==> Python version"
docker run --rm --entrypoint python $Candidate -c "import sys; print(sys.version)"

Write-Host "==> Pickle check (volumen aislado, sin hyperopt_results del host)"
docker run --rm `
  -v "$Root/user_data/strategies:/freqtrade/user_data/strategies:ro" `
  -v "$Root/user_data/config:/freqtrade/user_data/config:ro" `
  -v "$Root/user_data/hyperopts:/freqtrade/user_data/hyperopts:ro" `
  -v "$Root/user_data/tools:/freqtrade/user_data/tools:ro" `
  -v "$Root/pipeline:/freqtrade/pipeline:ro" `
  -v "$Root/user_data/validation_reports:/freqtrade/user_data/validation_reports:ro" `
  --entrypoint python `
  $Candidate `
  user_data/tools/hyperopt_pickle_check.py SmokeTestStrategy
