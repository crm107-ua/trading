# Reanudar validación MeanRevBB en PC1 (mismo run_id que servidor).
param(
  [string]$RunId = "20260709_162954"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = $Root
$env:PYTHONWARNINGS = "ignore::FutureWarning"
$env:HYPEROPT_JOB_WORKERS = if ($env:HYPEROPT_JOB_WORKERS) { $env:HYPEROPT_JOB_WORKERS } else { "1" }

$py = (Get-Command python -ErrorAction Stop).Source

docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Error "Docker no disponible. Arranca Docker Desktop y reintenta."
}

python -m pipeline.run_lock check
if ($LASTEXITCODE -eq 3) {
  Write-Error "Lock activo — otro run en curso."
}

Write-Host "==> Reanudando MeanRevBB run_id=$RunId en PC1"
& $py -W "ignore::FutureWarning" -m pipeline.run_validation MeanRevBB `
  --profile full `
  --resume-run-id $RunId
