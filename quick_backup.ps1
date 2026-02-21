# Quick Memory Doctrine Logs Backup
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "backups\memory_doctrine_logs_$timestamp"

Write-Host "🧠 Super Agency Memory Doctrine Logs Backup" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Timestamp: $timestamp"
Write-Host ""

# Create directories
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
New-Item -ItemType Directory -Path "$backupDir\doctrine" -Force | Out-Null
New-Item -ItemType Directory -Path "$backupDir\memory" -Force | Out-Null
New-Item -ItemType Directory -Path "$backupDir\logs" -Force | Out-Null
New-Item -ItemType Directory -Path "$backupDir\config" -Force | Out-Null
New-Item -ItemType Directory -Path "$backupDir\state" -Force | Out-Null

Write-Host "📁 Created backup directory: $backupDir" -ForegroundColor Green

# Save doctrine files
$doctrineFiles = @(
    "DOCTRINE_NCL_SECOND_BRAIN.md",
    "DOCTRINE_COUNCIL_52.md",
    "SUPER_AGENCY_DOCTRINE_MEMORY.md",
    "NORTH_STAR.md",
    "ROADMAP.md"
)

foreach ($file in $doctrineFiles) {
    if (Test-Path $file) {
        $newName = [System.IO.Path]::GetFileNameWithoutExtension($file) + "_$timestamp.md"
        Copy-Item $file "$backupDir\doctrine\$newName"
        Write-Host "✅ Doctrine saved: $file" -ForegroundColor Green
    }
}

# Save memory files
$memoryFiles = @(
    "SESSION_MEMORY_CAPTURE.md",
    "inner_council_intelligence.log"
)

foreach ($file in $memoryFiles) {
    if (Test-Path $file) {
        $newName = [System.IO.Path]::GetFileNameWithoutExtension($file) + "_$timestamp" + [System.IO.Path]::GetExtension($file)
        Copy-Item $file "$backupDir\memory\$newName"
        Write-Host "✅ Memory saved: $file" -ForegroundColor Green
    }
}

# Save logs
$logDirs = @("logs", "ncc_logs", "oversight_logs", "reports")
foreach ($dir in $logDirs) {
    if (Test-Path $dir) {
        Copy-Item -Recurse $dir "$backupDir\logs\$dir`_$timestamp"
        Write-Host "✅ Logs saved: $dir" -ForegroundColor Green
    }
}

# Save individual log files
$logFiles = @("youtube_intelligence.log")
foreach ($file in $logFiles) {
    if (Test-Path $file) {
        $newName = [System.IO.Path]::GetFileNameWithoutExtension($file) + "_$timestamp.log"
        Copy-Item $file "$backupDir\logs\$newName"
        Write-Host "✅ Log saved: $file" -ForegroundColor Green
    }
}

# Save config files
$configFiles = @(
    "inner_council_config.json",
    "youtube_intelligence_config.json",
    "portfolio.json",
    "portfolio.yaml"
)

foreach ($file in $configFiles) {
    if (Test-Path $file) {
        $newName = [System.IO.Path]::GetFileNameWithoutExtension($file) + "_$timestamp" + [System.IO.Path]::GetExtension($file)
        Copy-Item $file "$backupDir\config\$newName"
        Write-Host "✅ Config saved: $file" -ForegroundColor Green
    }
}

# Save state
if (Test-Path ".git") {
    git status --porcelain > "$backupDir\state\git_status_$timestamp.txt" 2>$null
    git log --oneline -10 > "$backupDir\state\git_log_$timestamp.txt" 2>$null
    Write-Host "✅ Git state saved" -ForegroundColor Green
}

# Create manifest
$manifest = "$backupDir\BACKUP_MANIFEST_$timestamp.txt"
"Super Agency Memory Doctrine Logs Backup" | Out-File $manifest
"Timestamp: $timestamp" | Out-File $manifest -Append
"Date: $(Get-Date)" | Out-File $manifest -Append
"==========================================" | Out-File $manifest -Append
"" | Out-File $manifest -Append
"BACKUP CONTENTS:" | Out-File $manifest -Append
"===============" | Out-File $manifest -Append
Get-ChildItem -Path $backupDir -Recurse -File | Select-Object FullName | Out-File $manifest -Append
"" | Out-File $manifest -Append
"BACKUP SUMMARY:" | Out-File $manifest -Append
"==============" | Out-File $manifest -Append
"Total files: $((Get-ChildItem -Path $backupDir -Recurse -File).Count)" | Out-File $manifest -Append
"Total size: $((Get-ChildItem -Path $backupDir -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB)" | Out-File $manifest -Append

Write-Host "" -ForegroundColor Green
Write-Host "✅ Backup completed successfully!" -ForegroundColor Green
Write-Host "📁 Backup location: $backupDir" -ForegroundColor Cyan
Write-Host "📋 Manifest: $manifest" -ForegroundColor Cyan

# Compress
$archiveName = "super_agency_backup_$timestamp.zip"
Compress-Archive -Path $backupDir -DestinationPath $archiveName -Force
Write-Host "📦 Compressed to: $archiveName" -ForegroundColor Green

Write-Host ""
Write-Host "🔄 Memory, doctrine, and logs backup complete!" -ForegroundColor Green
Write-Host "💾 System ready for continued operations" -ForegroundColor Cyan