# Tests de integración Docker — ejecutar pre-batch o en CI nocturno.
# No sustituye los unitarios; detecta contratos CLI y guards end-to-end.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> pytest integration (Docker)"
python -m pytest tests/ -m integration -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Integración OK"
