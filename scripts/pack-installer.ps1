$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
& (Join-Path $PSScriptRoot 'pack-win.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Directory build failed.' }
$projectNode = Join-Path $projectRoot '.tools/node/node.exe'
Push-Location (Join-Path $projectRoot 'frontend')
try {
    & $projectNode node_modules/electron-builder/cli.js --prepackaged ../release/t01/win-unpacked --win nsis --x64 --config electron-builder.installer.yml --publish never
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
    Write-Output 'Internal unsigned installer: release/installer. No publication performed.'
} finally { Pop-Location }
