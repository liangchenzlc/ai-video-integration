$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Executable" }
}
Push-Location $projectRoot
$previousPath = $env:PATH
try {
    $env:PATH = (Join-Path $projectRoot '.tools/node') + ';' + (Join-Path $projectRoot '.tools/bin') + ';' + $env:PATH
    $projectPython = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
    $projectNode = Join-Path $projectRoot '.tools/node/node.exe'
    Invoke-Checked $projectPython @('scripts/verify_toolchain.py')
    Invoke-Checked $projectPython @('-m', 'PyInstaller', '--noconfirm', '--distpath', 'backend/dist', '--workpath', 'backend/build', 'backend/avi_backend.spec')
    Push-Location (Join-Path $projectRoot 'frontend')
    try {
        Invoke-Checked $projectNode @('node_modules/electron-vite/bin/electron-vite.js', 'build')
        Invoke-Checked $projectNode @('node_modules/electron-builder/cli.js', '--dir', '--win', '--x64', '--config', 'electron-builder.yml')
    } finally { Pop-Location }
    Write-Output 'Directory package: release/t01/win-unpacked/AI Video Integration.exe'
} finally { $env:PATH = $previousPath; Pop-Location }
