param([switch]$SkipDesktop)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Check failed ($LASTEXITCODE): $Executable" }
}
Push-Location $projectRoot
$previousPytestRoot = $env:PYTEST_DEBUG_TEMPROOT
try {
    $env:PYTEST_DEBUG_TEMPROOT = Join-Path $projectRoot ('.cache/test-tmp/' + [guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Path $env:PYTEST_DEBUG_TEMPROOT -Force | Out-Null
    $projectPython = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
    $projectNode = Join-Path $projectRoot '.tools/node/node.exe'
    Invoke-Checked 'powershell.exe' @('-NoProfile', '-File', 'scripts/check-t01-b-http.ps1')
    Invoke-Checked 'powershell.exe' @('-NoProfile', '-File', 'scripts/check-t01-c-backend.ps1')
    Invoke-Checked $projectPython @('backend/scripts/build_control_vectors.py')
    Invoke-Checked $projectPython @('-m', 'ruff', 'check', 'scripts/desktop_process_observer.py', '--config', 'backend/pyproject.toml')
    Push-Location (Join-Path $projectRoot 'frontend')
    try {
        $previousLocalAppData = $env:LOCALAPPDATA
        $env:LOCALAPPDATA = Join-Path $projectRoot '.cache/vitest-userdata'
        Invoke-Checked $projectNode @('node_modules/typescript/bin/tsc', '-p', 'tsconfig.node.json')
        Invoke-Checked $projectNode @('node_modules/typescript/bin/tsc', '-p', 'tsconfig.web.json')
        Invoke-Checked $projectNode @('node_modules/eslint/bin/eslint.js', '.')
        Invoke-Checked $projectNode @('node_modules/prettier/bin/prettier.cjs', '--check', '.')
        Invoke-Checked $projectNode @('node_modules/vitest/vitest.mjs', 'run', '--reporter=default', '--reporter=json', '--outputFile=../.cache/t01-frontend-tests.json')
        $env:LOCALAPPDATA = $previousLocalAppData
        Invoke-Checked $projectNode @('node_modules/electron-vite/bin/electron-vite.js', 'build')
        if (-not $SkipDesktop) { Invoke-Checked $projectNode @('node_modules/@playwright/test/cli.js', 'test') }
    } finally { $env:LOCALAPPDATA = $previousLocalAppData; Pop-Location }
    if ($SkipDesktop) { Write-Output 'Code checks passed; desktop acceptance explicitly NOT run.' }
    else { Write-Output 'T01 source checks and desktop tests passed. Packaged test is a separate command.' }
} finally { $env:PYTEST_DEBUG_TEMPROOT = $previousPytestRoot; Pop-Location }
