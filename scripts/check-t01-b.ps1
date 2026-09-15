$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Check failed ($LASTEXITCODE): $Executable" }
}
Push-Location $projectRoot
try {
    Invoke-Checked 'powershell.exe' @('-NoProfile', '-File', 'scripts/check-t01-b-http.ps1')
    $projectPython = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
    $projectNode = Join-Path $projectRoot '.tools/node/node.exe'
    Invoke-Checked $projectPython @('backend/scripts/build_control_vectors.py')
    Invoke-Checked $projectPython @('-m', 'ruff', 'check', 'backend/app', 'backend/scripts', 'backend/tests', '--config', 'backend/pyproject.toml')
    Invoke-Checked $projectPython @('-m', 'ruff', 'format', '--check', 'backend/app', 'backend/scripts', 'backend/tests', '--config', 'backend/pyproject.toml')
    Invoke-Checked $projectPython @('-m', 'pytest', 'backend/tests/runtime/test_control_protocol.py', 'backend/tests/runtime/test_control_vectors.py', 'backend/tests/runtime/test_pipe_writer.py', '-q', '-p', 'no:cacheprovider', '--tb=short', '--junitxml=.cache/t01-b-control-tests.xml')
    Push-Location (Join-Path $projectRoot 'frontend')
    try {
        # Keep Vitest's own local token/cache inside this workspace.
        $previousLocalAppData = $env:LOCALAPPDATA
        $env:LOCALAPPDATA = Join-Path $projectRoot '.cache/vitest-userdata'
        Invoke-Checked $projectNode @('node_modules/vitest/vitest.mjs', 'run')
        Invoke-Checked $projectNode @('node_modules/typescript/bin/tsc', '-p', 'tsconfig.node.json')
        Invoke-Checked $projectNode @('node_modules/prettier/bin/prettier.cjs', '--check', 'electron', 'tests', 'tsconfig.node.json', 'vitest.config.ts')
    } finally {
        $env:LOCALAPPDATA = $previousLocalAppData
        Pop-Location
    }
    Write-Output 'T01-B contracts and pipe codec checks passed.'
} finally { Pop-Location }
