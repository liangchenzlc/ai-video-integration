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
    Invoke-Checked $projectPython @('-m', 'ruff', 'check', 'backend', '--config', 'backend/pyproject.toml')
    Invoke-Checked $projectPython @('-m', 'ruff', 'format', '--check', 'backend', '--config', 'backend/pyproject.toml')
    Invoke-Checked $projectPython @('-m', 'mypy', '--config-file', 'backend/pyproject.toml', 'backend/app', '--cache-dir=.cache/mypy')
    foreach ($spec in @('backend/avi_probe.spec', 'backend/avi_backend.spec')) {
        Invoke-Checked $projectPython @('-m', 'PyInstaller', '--noconfirm', '--distpath', 'backend/dist', '--workpath', 'backend/build', $spec)
    }
    Invoke-Checked $projectPython @('-m', 'pytest', 'backend/tests', '-q', '-p', 'no:cacheprovider', '--tb=short', '--junitxml=.cache/t01-c-backend-tests.xml')
    Write-Output 'T01-C backend integration checks passed. Electron lifecycle integration remains.'
} finally { Pop-Location }
