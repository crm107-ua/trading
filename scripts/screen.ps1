# Screen pre-validación (Windows)
param(
  [Parameter(Mandatory = $true)][string]$Strategy,
  [string]$Timerange = "20210101-",
  [string]$VariantsFile = "",
  [string]$PriorReport = "",
  [switch]$Fixtures,
  [switch]$SkipDefaults
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$args = @("user_data/tools/screen_strategy.py", $Strategy, "--timerange", $Timerange)
if ($VariantsFile) { $args += @("--variants-file", $VariantsFile) }
if ($PriorReport) { $args += @("--prior-report", $PriorReport) }
if ($Fixtures) { $args += "--fixtures" }
if ($SkipDefaults) { $args += "--skip-defaults" }

python @args
