# Install Pocketwatcher Windows Services using NSSM
# Run as Administrator
#
# Prerequisites:
# - NSSM installed (https://nssm.cc/)
# - Python 3.11+ installed
# - Environment configured in .env file
#
# Usage: .\install-services.ps1 -AppPath C:\pocketwatcher

param(
    [string]$AppPath = "C:\pocketwatcher",
    [string]$PythonPath = "C:\Python311\python.exe",
    [string]$LogPath = "C:\pocketwatcher\data\logs"
)

$ErrorActionPreference = "Stop"

# Verify NSSM is installed
try {
    $nssm = Get-Command nssm -ErrorAction Stop
    Write-Host "Found NSSM at: $($nssm.Source)" -ForegroundColor Green
} catch {
    Write-Host "ERROR: NSSM not found. Install from https://nssm.cc/" -ForegroundColor Red
    exit 1
}

# Verify Python is installed
if (-not (Test-Path $PythonPath)) {
    Write-Host "ERROR: Python not found at $PythonPath" -ForegroundColor Red
    Write-Host "Set -PythonPath to your Python installation" -ForegroundColor Yellow
    exit 1
}

# Verify app path exists
if (-not (Test-Path "$AppPath\main.py")) {
    Write-Host "ERROR: main.py not found in $AppPath" -ForegroundColor Red
    exit 1
}

# Create log directory
if (-not (Test-Path $LogPath)) {
    New-Item -ItemType Directory -Path $LogPath -Force | Out-Null
    Write-Host "Created log directory: $LogPath" -ForegroundColor Green
}

Write-Host ""
Write-Host "Installing Pocketwatcher services..." -ForegroundColor Cyan
Write-Host "  App path: $AppPath"
Write-Host "  Python: $PythonPath"
Write-Host "  Logs: $LogPath"
Write-Host ""

# ============================================
# Worker Service
# ============================================
$workerService = "pocketwatcher-worker"

Write-Host "Installing $workerService..." -ForegroundColor Yellow

# Remove if exists
nssm stop $workerService 2>$null
nssm remove $workerService confirm 2>$null

# Install
nssm install $workerService $PythonPath "$AppPath\main.py"
nssm set $workerService AppDirectory $AppPath
nssm set $workerService AppStdout "$LogPath\worker.log"
nssm set $workerService AppStderr "$LogPath\worker-error.log"
nssm set $workerService AppRotateFiles 1
nssm set $workerService AppRotateBytes 10485760
nssm set $workerService AppRotateOnline 1
nssm set $workerService AppStopMethodSkip 0
nssm set $workerService AppStopMethodConsole 3000
nssm set $workerService AppStopMethodWindow 3000
nssm set $workerService AppStopMethodThreads 1000
nssm set $workerService Description "Pocketwatcher transaction processor and alert engine"
nssm set $workerService Start SERVICE_AUTO_START
nssm set $workerService ObjectName LocalSystem

Write-Host "  $workerService installed" -ForegroundColor Green

# ============================================
# API Service
# ============================================
$apiService = "pocketwatcher-api"

Write-Host "Installing $apiService..." -ForegroundColor Yellow

# Remove if exists
nssm stop $apiService 2>$null
nssm remove $apiService confirm 2>$null

# Install
nssm install $apiService $PythonPath "-m" "api.server"
nssm set $apiService AppDirectory $AppPath
nssm set $apiService AppStdout "$LogPath\api.log"
nssm set $apiService AppStderr "$LogPath\api-error.log"
nssm set $apiService AppRotateFiles 1
nssm set $apiService AppRotateBytes 10485760
nssm set $apiService AppRotateOnline 1
nssm set $apiService AppStopMethodSkip 0
nssm set $apiService AppStopMethodConsole 3000
nssm set $apiService AppStopMethodWindow 3000
nssm set $apiService AppStopMethodThreads 1000
nssm set $apiService Description "Pocketwatcher configuration API and dashboard"
nssm set $apiService Start SERVICE_AUTO_START
nssm set $apiService ObjectName LocalSystem

Write-Host "  $apiService installed" -ForegroundColor Green

# ============================================
# Summary
# ============================================
Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "To start services:" -ForegroundColor Cyan
Write-Host "  nssm start $workerService"
Write-Host "  nssm start $apiService"
Write-Host ""
Write-Host "To check status:" -ForegroundColor Cyan
Write-Host "  nssm status $workerService"
Write-Host "  nssm status $apiService"
Write-Host ""
Write-Host "To view logs:" -ForegroundColor Cyan
Write-Host "  Get-Content $LogPath\worker.log -Tail 50"
Write-Host "  Get-Content $LogPath\api.log -Tail 50"
Write-Host ""
Write-Host "Dashboard: http://localhost:8080" -ForegroundColor Yellow
Write-Host "Health check: http://localhost:8080/api/health" -ForegroundColor Yellow
