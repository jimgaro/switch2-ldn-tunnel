param([switch]$Repair, [switch]$Json, [string]$Device)
$ErrorActionPreference = 'Stop'
$taskPython = Get-Command python -ErrorAction SilentlyContinue
if (-not $taskPython) {
    Write-Error 'Instala Python 3.10 o posterior para Windows desde https://www.python.org/downloads/windows/ y habilita su acceso desde la terminal.'
    exit 1
}
$taskArgs = @('-m', 'switch2_tunnel.doctor')
if ($Repair) { $taskArgs += '--repair' }
if ($Json) { $taskArgs += '--json' }
if ($Device) { $taskArgs += @('--device', $Device) }
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    & $taskPython.Source @taskArgs
    $taskExit = $LASTEXITCODE
} finally { Pop-Location }
exit $taskExit
