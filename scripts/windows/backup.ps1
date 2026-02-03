# Pocketwatcher Backup Script
# Run as scheduled task for automated daily backups
#
# Usage: .\backup.ps1 [-BackupDir C:\pocketwatcher\data\backups] [-RetentionDays 7]

param(
    [string]$BackupDir = "C:\pocketwatcher\data\backups",
    [int]$RetentionDays = 7,
    [string]$PgUser = "pocketwatcher",
    [string]$PgDatabase = "pocketwatcher",
    [string]$RedisDataDir = "C:\Redis"
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

Write-Host "Starting Pocketwatcher backup..." -ForegroundColor Cyan
Write-Host "  Timestamp: $timestamp"
Write-Host "  Backup dir: $BackupDir"
Write-Host ""

# Create backup directory
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    Write-Host "Created backup directory" -ForegroundColor Green
}

# ============================================
# PostgreSQL Backup
# ============================================
Write-Host "Backing up PostgreSQL..." -ForegroundColor Yellow

$pgBackupFile = "$BackupDir\pg_$timestamp.dump"

try {
    $env:PGPASSWORD = $env:PGPASSWORD  # Use env var for password
    pg_dump -U $PgUser -d $PgDatabase -F c -f $pgBackupFile

    if (Test-Path $pgBackupFile) {
        $size = (Get-Item $pgBackupFile).Length / 1MB
        Write-Host "  PostgreSQL backup complete: $([math]::Round($size, 2)) MB" -ForegroundColor Green
    } else {
        Write-Host "  PostgreSQL backup failed!" -ForegroundColor Red
    }
} catch {
    Write-Host "  PostgreSQL backup error: $_" -ForegroundColor Red
}

# ============================================
# Redis Backup
# ============================================
Write-Host "Backing up Redis..." -ForegroundColor Yellow

$redisBackupFile = "$BackupDir\redis_$timestamp.rdb"

try {
    # Trigger Redis BGSAVE
    redis-cli BGSAVE | Out-Null

    # Wait for save to complete (max 30 seconds)
    $waited = 0
    while ($waited -lt 30) {
        $lastSave = redis-cli LASTSAVE
        Start-Sleep -Seconds 2
        $waited += 2
        $newLastSave = redis-cli LASTSAVE
        if ($newLastSave -ne $lastSave) {
            break
        }
    }

    # Copy dump.rdb
    $rdbSource = "$RedisDataDir\dump.rdb"
    if (Test-Path $rdbSource) {
        Copy-Item $rdbSource $redisBackupFile
        $size = (Get-Item $redisBackupFile).Length / 1MB
        Write-Host "  Redis backup complete: $([math]::Round($size, 2)) MB" -ForegroundColor Green
    } else {
        Write-Host "  Redis dump.rdb not found at $rdbSource" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Redis backup error: $_" -ForegroundColor Red
}

# ============================================
# Cleanup Old Backups
# ============================================
Write-Host "Cleaning up old backups (older than $RetentionDays days)..." -ForegroundColor Yellow

$cutoffDate = (Get-Date).AddDays(-$RetentionDays)
$deletedCount = 0

Get-ChildItem -Path $BackupDir -Include "pg_*.dump", "redis_*.rdb" -Recurse | Where-Object {
    $_.LastWriteTime -lt $cutoffDate
} | ForEach-Object {
    Remove-Item $_.FullName -Force
    $deletedCount++
}

if ($deletedCount -gt 0) {
    Write-Host "  Deleted $deletedCount old backup files" -ForegroundColor Green
} else {
    Write-Host "  No old backups to delete" -ForegroundColor Gray
}

# ============================================
# Summary
# ============================================
Write-Host ""
Write-Host "Backup complete!" -ForegroundColor Green
Write-Host ""

# List recent backups
Write-Host "Recent backups:" -ForegroundColor Cyan
Get-ChildItem -Path $BackupDir -Include "*.dump", "*.rdb" -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 10 | ForEach-Object {
    $size = [math]::Round($_.Length / 1MB, 2)
    Write-Host "  $($_.Name) - $size MB - $($_.LastWriteTime)"
}
