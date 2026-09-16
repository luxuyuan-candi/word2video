$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = Join-Path $root "backups"
$backupDir = Join-Path $backupRoot "word2video-$timestamp"

New-Item -ItemType Directory -Force $backupDir | Out-Null

if (Test-Path "$root\data") {
  Copy-Item -Recurse -Force "$root\data" "$backupDir\data"
}

Compress-Archive -Path "$backupDir\*" -DestinationPath "$backupDir.zip" -Force
Write-Host "Backup created: $backupDir.zip"
