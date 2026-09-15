$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Check failed ($LASTEXITCODE): $Executable" }
}
Push-Location $projectRoot
try {
    $projectPython = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
    $projectNode = Join-Path $projectRoot '.tools/node/node.exe'
    Invoke-Checked $projectPython @('scripts/verify_toolchain.py')
    Invoke-Checked $projectPython @('-m', 'ruff', 'check', 'backend/app', 'backend/tests/api', 'backend/scripts', '--config', 'backend/pyproject.toml')
    Invoke-Checked $projectPython @('-m', 'ruff', 'format', '--check', 'backend/app', 'backend/tests/api', 'backend/scripts', '--config', 'backend/pyproject.toml')
    Invoke-Checked $projectPython @('-m', 'mypy', '--config-file', 'backend/pyproject.toml', 'backend/app', '--cache-dir=.cache/mypy')
    Invoke-Checked $projectPython @('-m', 'pytest', 'backend/tests/api', '-q', '-p', 'no:cacheprovider', '--tb=short', '--junitxml=.cache/t01-b-http-tests.xml')
    Invoke-Checked $projectPython @('backend/scripts/export_openapi.py', '--output', 'contracts/openapi.json')
    Invoke-Checked $projectNode @('frontend/node_modules/openapi-typescript/bin/cli.js', 'contracts/openapi.json', '-o', 'frontend/src/api/runtime-types.ts')
    Invoke-Checked $projectNode @('frontend/node_modules/typescript/bin/tsc', '--noEmit', '--strict', '--skipLibCheck', 'frontend/src/api/runtime-types.ts')
    Write-Output 'T01-B HTTP checks passed. Live socket and desktop integration remain separate gates.'
} finally { Pop-Location }
