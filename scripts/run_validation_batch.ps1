# Batch Fase 4 — lanzar tras calibración y congelación del veredicto (MeanRevBB).
# NO EJECUTAR hasta que verdict_engine.py / verdict.py estén commiteados con umbrales finales.
#
# Respeta .run_lock.json entre estrategias (aborta si la anterior no liberó el lock).

param(
  [string]$Strategy = "",
  [int]$WfEpochs = 0,
  [switch]$AdoptPartialHyperopt
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$Batch = @(
  "TrendRider",
  "BreakoutVol",
  "RegimeSwitcher",
  "GridDCA"
)

if ($Strategy) {
  $Batch = @($Strategy)
}

Write-Host "==> Batch validación full (post-calibración)"
Write-Host "    Estrategias: $($Batch -join ', ')"
Write-Host "    HYPEROPT_JOB_WORKERS=$(if ($env:HYPEROPT_JOB_WORKERS) { $env:HYPEROPT_JOB_WORKERS } else { '1' })"
Write-Host "    WF epochs/ventana: $(if ($WfEpochs -gt 0) { $WfEpochs } else { '300 (perfil full)' })"
Write-Host "    adopt-partial-hyperopt: $(if ($AdoptPartialHyperopt) { 'ON' } else { 'OFF — activar antes del batch' })"
Write-Host ""
Write-Host "CONFIRME: umbrales congelados + decisión WF (calibration_protocol.md) antes de continuar."
Write-Host "Ctrl+C para abortar; Enter para lanzar."
[void](Read-Host)

python -m pipeline.run_lock check
if ($LASTEXITCODE -eq 3) {
  Write-Host "[red]Lock activo — otro run_validation en curso.[/red]"
  exit 3
}

foreach ($s in $Batch) {
  python -m pipeline.run_lock check
  if ($LASTEXITCODE -eq 3) {
    Write-Host "[red]Lock activo antes de $s — batch abortado.[/red]"
    exit 3
  }

  Write-Host ""
  Write-Host "========================================"
  Write-Host "==> $s --profile full"
  Write-Host "========================================"
  $args = @($s, "--profile", "full")
  if ($WfEpochs -gt 0) { $args += @("--wf-epochs", "$WfEpochs") }
  if ($AdoptPartialHyperopt) { $args += "--adopt-partial-hyperopt" }
  python -m pipeline.run_validation @args
  if ($LASTEXITCODE -eq 2) {
    Write-Host "[yellow]Veredicto SOBREAJUSTADA — continuar con siguiente estrategia[/yellow]"
  } elseif ($LASTEXITCODE -ne 0) {
    Write-Host "[red]Fallo en $s (exit $LASTEXITCODE). Reanudar con --resume-run-id si aplica.[/red]"
    exit $LASTEXITCODE
  }

  python -m pipeline.run_lock check
  if ($LASTEXITCODE -eq 3) {
    Write-Host "[red]Lock no liberado tras $s — revisar run_validation.[/red]"
    exit 3
  }
}

Write-Host "[green]Batch completado.[/green]"
