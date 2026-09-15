$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$source = Join-Path $projectRoot 'release/t01/win-unpacked'
if (-not (Test-Path -LiteralPath (Join-Path $source 'AI Video Integration.exe'))) { throw 'Run scripts/pack-win.ps1 first.' }
# A new directory prevents stale artifacts; no recursive removal or moving user files.
$destination = Join-Path $projectRoot ('.cache/T01 中文 空格/' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $destination -Force | Out-Null
Copy-Item -Path (Join-Path $source '*') -Destination $destination -Recurse
$previousExe = $env:T01_DESKTOP_EXE
$env:T01_DESKTOP_EXE = Join-Path $destination 'AI Video Integration.exe'
Push-Location (Join-Path $projectRoot 'frontend')
try {
    & (Join-Path $projectRoot '.tools/node/node.exe') 'node_modules/@playwright/test/cli.js' test
    if ($LASTEXITCODE -ne 0) { throw 'Packaged desktop verification failed.' }
    Copy-Item -LiteralPath (Join-Path $projectRoot '.cache/t01-desktop-tests.json') -Destination (Join-Path $projectRoot 'docs/开发记录/t01-packaged-tests.json')
    Copy-Item -LiteralPath (Join-Path $projectRoot '.cache/t01-desktop-metrics.json') -Destination (Join-Path $projectRoot 'docs/开发记录/t01-packaged-metrics.json')
    Write-Output "Packaged tests passed: $destination"
} finally { $env:T01_DESKTOP_EXE = $previousExe; Pop-Location }
