param([string]$Revision, [switch]$Repair, [switch]$Json)
$ErrorActionPreference = 'Stop'
$taskPython = Get-Command python -ErrorAction SilentlyContinue
if (-not $taskPython) {
    Write-Error 'Instala Python 3.10 o posterior desde https://www.python.org/downloads/windows/ y habilita su acceso desde la terminal.'
    exit 1
}
$taskArgs = @('-m', 'switch2_tunnel.doctor', '--model', 'TL-WN725N')
if ($Revision) { $taskArgs += @('--revision', $Revision) }
if ($Repair) { $taskArgs += '--repair' }
if ($Json) { $taskArgs += '--json' }
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
    & $taskPython.Source @taskArgs
    $taskExit = $LASTEXITCODE
} finally { Pop-Location }
exit $taskExit
