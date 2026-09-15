$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$projectNode = Join-Path $projectRoot '.tools/node/node.exe'
Push-Location (Join-Path $projectRoot 'frontend')
try {
    $previousPath = $env:PATH
    $env:PATH = (Join-Path $projectRoot '.tools/node') + ';' + $env:PATH
    & $projectNode 'node_modules/electron-vite/bin/electron-vite.js' dev
    if ($LASTEXITCODE -ne 0) { throw 'Desktop development startup failed.' }
} finally { $env:PATH = $previousPath; Pop-Location }
