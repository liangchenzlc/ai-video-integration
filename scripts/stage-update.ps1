param(
    [Parameter(Mandatory=$true)][string]$InstalledDirectory,
    [Parameter(Mandatory=$true)][string]$RollbackDirectory
)
$ErrorActionPreference = 'Stop'
function Assert-UnlinkedAncestors([string]$CandidatePath) {
    $candidate = [IO.Path]::GetFullPath($CandidatePath)
    while ($candidate) {
        if (Test-Path -LiteralPath $candidate) {
            $entry = Get-Item -LiteralPath $candidate -Force
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Application and rollback paths must not traverse linked directories.'
            }
        }
        $parent = [IO.Path]::GetDirectoryName($candidate.TrimEnd('\'))
        if ($parent -eq $candidate) { break }
        $candidate = $parent
    }
}
Assert-UnlinkedAncestors $InstalledDirectory
Assert-UnlinkedAncestors $RollbackDirectory
$installedPath = (Resolve-Path -LiteralPath $InstalledDirectory).Path
$rollbackPath = [IO.Path]::GetFullPath($RollbackDirectory)
$installedExe = Join-Path $installedPath 'AI Video Integration.exe'
if (-not (Test-Path -LiteralPath $installedExe -PathType Leaf)) { throw 'The source is not an application directory.' }
if ($rollbackPath.StartsWith($installedPath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or $rollbackPath -eq $installedPath) { throw 'Rollback directory must be outside the installation.' }
if (Test-Path -LiteralPath $rollbackPath) { throw 'Choose a new, unused rollback directory.' }
$runningInstances = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.Equals($installedExe,[StringComparison]::OrdinalIgnoreCase) })
if ($runningInstances.Count -gt 0) { throw 'Close this application normally before staging the update. No processes were terminated.' }
$unsafeEntries = @(Get-ChildItem -LiteralPath $installedPath -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
if ($unsafeEntries.Count -gt 0) { throw 'Installation contains linked paths; backup was not started.' }
New-Item -ItemType Directory -Path $rollbackPath | Out-Null
Assert-UnlinkedAncestors $installedPath
Assert-UnlinkedAncestors $rollbackPath
Get-ChildItem -LiteralPath $installedPath -Force | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $rollbackPath -Recurse -Force }
$filesToVerify = Get-ChildItem -LiteralPath $installedPath -File -Recurse -Force
foreach ($sourceFile in $filesToVerify) {
    $relativeName = $sourceFile.FullName.Substring($installedPath.TrimEnd('\').Length + 1)
    $backupFile = Join-Path $rollbackPath $relativeName
    if ((Get-FileHash -LiteralPath $sourceFile.FullName -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $backupFile -Algorithm SHA256).Hash) { throw 'Rollback verification failed. Keep the original application and investigate the copy.' }
}
Write-Output 'Rollback application copy verified. Project directories and user settings were not changed. You can now run the new installer; newer project schemas must not be opened for writing by this older copy.'
