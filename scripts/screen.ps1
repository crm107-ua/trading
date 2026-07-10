# Screen pre-validación (Windows)
param(
  [Parameter(Mandatory = $true)][string]$Strategy,
  [string]$Timerange = "20210101-",
  [string]$VariantsFile = "",
  [switch]$Fixtures
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$args = @("user_data/tools/screen_strategy.py", $Strategy, "--timerange", $Timerange)
if ($VariantsFile) { $args += @("--variants-file", $VariantsFile) }
if ($Fixtures) { $args += "--fixtures" }

python @args
