param([switch]$BackendOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Check failed ($LASTEXITCODE): $Executable"
    }
}

Push-Location $projectRoot
try {
    $projectPython = Join-Path $projectRoot 'backend/.venv/Scripts/python.exe'
    $projectNode = Join-Path $projectRoot '.tools/node/node.exe'
    $env:PATH = (Join-Path $projectRoot '.tools/bin') + ';' + (Join-Path $projectRoot '.tools/node') + ';' + $env:PATH
    $env:UV_CACHE_DIR = Join-Path $projectRoot '.cache/uv'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.tools/python'
    $env:ELECTRON_BUILDER_CACHE = Join-Path $projectRoot '.cache/electron-builder'
    Invoke-Checked $projectPython @('scripts/verify_toolchain.py')
    Invoke-Checked $projectPython @('-m', 'ruff', 'check', 'backend', 'scripts', '--config', 'backend/pyproject.toml')
    Invoke-Checked $projectPython @('-m', 'ruff', 'format', '--check', 'backend', 'scripts', '--config', 'backend/pyproject.toml')
    Invoke-Checked $projectPython @('-m', 'mypy', '--config-file', 'backend/pyproject.toml', 'backend/app', '--cache-dir=.cache/mypy')
    Invoke-Checked $projectPython @('-m', 'PyInstaller', '--noconfirm', '--distpath', 'backend/dist', '--workpath', 'backend/build', 'backend/avi_probe.spec')
    # Cacheprovider is unnecessary here and can stall on sandbox temporary-directory permissions.
    Invoke-Checked $projectPython @('-m', 'pytest', 'backend/tests/runtime', '-v', '-p', 'no:cacheprovider', '--tb=short', '--junitxml=.cache/t01-a-tests.xml')
    Invoke-Checked $projectNode @('--check', 'frontend/probe/index.cjs')
    Invoke-Checked $projectNode @('frontend/node_modules/prettier/bin/prettier.cjs', '--check', 'frontend/probe', 'frontend/electron-builder.probe.yml', 'frontend/package.json')
    if (-not $BackendOnly) {
        Push-Location (Join-Path $projectRoot 'frontend')
        try {
            Invoke-Checked $projectNode @('node_modules/electron-builder/out/cli/cli.js', '--config', 'electron-builder.probe.yml', '--dir', '--win', '--x64')
        } finally { Pop-Location }
        Invoke-Checked $projectPython @('scripts/verify_desktop_probe.py')
    }
    Write-Output 'T01-A requested checks passed. This is a packaging probe, not a completed product module.'
} finally { Pop-Location }
