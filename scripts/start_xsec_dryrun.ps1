# Arranque dry-run XSecMomentum-m35 (aislado del lab MeanRevBB).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> Verificando puerto 8082..."
$inUse = Get-NetTCPConnection -LocalPort 8082 -ErrorAction SilentlyContinue
if ($inUse) { Write-Warning "Puerto 8082 en uso — revisar antes de continuar" }

Write-Host "==> Validando estrategia (list-strategies)..."
docker compose -f docker-compose.dryrun.yml run --rm --no-deps --entrypoint freqtrade xsec-dryrun `
  list-strategies --strategy-path /freqtrade/user_data/strategies `
  --config /freqtrade/user_data/config/base.json `
  --config /freqtrade/user_data/config/dryrun_xsec.json 2>&1 | Select-String "XSecMomentum"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> Levantando xsec-dryrun..."
docker compose -f docker-compose.dryrun.yml up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$started = @{ started_at = (Get-Date).ToUniversalTime().ToString("o") } | ConvertTo-Json
Set-Content -Path "user_data/dryrun_xsec_started.json" -Value $started -Encoding utf8

Write-Host "==> Esperando healthcheck (90s max)..."
$ok = $false
1..18 | ForEach-Object {
  Start-Sleep -Seconds 5
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8082/api/v1/ping" -UseBasicParsing -TimeoutSec 5
    if ($r.StatusCode -eq 200) { $ok = $true; break }
  } catch {}
}
if (-not $ok) { Write-Warning "Ping aún no responde — revisar: docker compose -f docker-compose.dryrun.yml logs -f" }

Write-Host "==> Monitor (un ciclo)..."
python -m risk.monitor --once

Write-Host "==> Hecho. API: http://127.0.0.1:8082"
