# Vigilante remoto — validación MeanRevBB en servidor Carlos (desde PC1).
#
# NO lanza run_validation en PC1; solo consulta progreso por SSH.
#
# Uso:
#   pwsh scripts/watch_server_validation.ps1
#   pwsh scripts/watch_server_validation.ps1 -IntervalSec 60 -Format bar
#   pwsh scripts/watch_server_validation.ps1 -Once

param(
  [string]$Strategy = "MeanRevBB",
  [string]$RunId = "20260709_162954",
  [string]$RemoteHost = "192.168.50.20",
  [string]$RemoteUser = "carlos",
  [string]$RemoteRoot = "/var/www/html/trader",
  [int]$IntervalSec = 120,
  [ValidateSet("compact", "bar", "full")]
  [string]$Format = "bar",
  [switch]$Once
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$KeyPath = Join-Path $Root "carlos_key"
if (-not (Test-Path $KeyPath)) {
  Write-Host "Falta clave SSH: $KeyPath" -ForegroundColor Red
  exit 1
}

$SshTarget = "${RemoteUser}@${RemoteHost}"
$RemoteCmd = @"
cd '$RemoteRoot' && export PYTHONPATH='$RemoteRoot' && \
.venv/bin/python scripts/validation_progress.py \
  --strategy '$Strategy' --run-id '$RunId' --format '$Format'
"@

function Get-RemoteProgress {
  ssh -o LogLevel=ERROR -o ConnectTimeout=15 -o BatchMode=yes -i $KeyPath $SshTarget $RemoteCmd 2>$null
}

function Get-RemotePm2 {
  $cmd = "pm2 pid meanrevbb-validation >/dev/null 2>&1 && echo online || echo stopped"
  try {
    $r = ssh -o LogLevel=ERROR -o ConnectTimeout=10 -i $KeyPath $SshTarget $cmd 2>$null
    if ($r) { return $r.Trim() }
  } catch {}
  return "?"
}

Write-Host "Monitor remoto: $SshTarget ($RemoteRoot)"
Write-Host "  run_id=$RunId  cada ${IntervalSec}s  formato=$Format"
Write-Host "  (PC1 no ejecuta validación — solo lectura)"
Write-Host ""

while ($true) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $pm2 = Get-RemotePm2
  $body = Get-RemoteProgress

  if (-not $body) {
    Write-Host "[$ts] ERROR SSH / servidor inalcanzable" -ForegroundColor Red
    if ($body) { Write-Host $body }
  } else {
    $color = if ($pm2 -eq "online") { "Green" } elseif ($pm2 -eq "stopped") { "Red" } else { "Yellow" }
    Write-Host "[$ts] PM2=$pm2" -ForegroundColor $color
    if ($Format -eq "full") {
      Write-Host $body
    } else {
      Write-Host $body -ForegroundColor Cyan
    }
  }

  if ($Once) { break }
  Start-Sleep -Seconds $IntervalSec
}
