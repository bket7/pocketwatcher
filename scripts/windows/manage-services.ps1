# Manage Pocketwatcher Windows Services
# Run as Administrator
#
# Usage:
#   .\manage-services.ps1 start     # Start all services
#   .\manage-services.ps1 stop      # Stop all services
#   .\manage-services.ps1 restart   # Restart all services
#   .\manage-services.ps1 status    # Check service status

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action
)

$services = @("pocketwatcher-worker", "pocketwatcher-api")

function Get-ServiceStatus {
    param([string]$ServiceName)

    try {
        $status = nssm status $ServiceName 2>&1
        if ($status -match "SERVICE_RUNNING") {
            return "Running"
        } elseif ($status -match "SERVICE_STOPPED") {
            return "Stopped"
        } elseif ($status -match "SERVICE_PAUSED") {
            return "Paused"
        } else {
            return "Unknown"
        }
    } catch {
        return "Not Installed"
    }
}

switch ($Action) {
    "start" {
        Write-Host "Starting Pocketwatcher services..." -ForegroundColor Cyan
        foreach ($svc in $services) {
            Write-Host "  Starting $svc..." -NoNewline
            nssm start $svc 2>$null
            Start-Sleep -Seconds 1
            $status = Get-ServiceStatus $svc
            if ($status -eq "Running") {
                Write-Host " OK" -ForegroundColor Green
            } else {
                Write-Host " FAILED ($status)" -ForegroundColor Red
            }
        }
    }

    "stop" {
        Write-Host "Stopping Pocketwatcher services..." -ForegroundColor Cyan
        foreach ($svc in $services) {
            Write-Host "  Stopping $svc..." -NoNewline
            nssm stop $svc 2>$null
            Start-Sleep -Seconds 2
            $status = Get-ServiceStatus $svc
            if ($status -eq "Stopped") {
                Write-Host " OK" -ForegroundColor Green
            } else {
                Write-Host " FAILED ($status)" -ForegroundColor Red
            }
        }
    }

    "restart" {
        Write-Host "Restarting Pocketwatcher services..." -ForegroundColor Cyan
        foreach ($svc in $services) {
            Write-Host "  Restarting $svc..." -NoNewline
            nssm restart $svc 2>$null
            Start-Sleep -Seconds 2
            $status = Get-ServiceStatus $svc
            if ($status -eq "Running") {
                Write-Host " OK" -ForegroundColor Green
            } else {
                Write-Host " FAILED ($status)" -ForegroundColor Red
            }
        }
    }

    "status" {
        Write-Host ""
        Write-Host "Pocketwatcher Service Status" -ForegroundColor Cyan
        Write-Host "=============================" -ForegroundColor Cyan
        Write-Host ""

        foreach ($svc in $services) {
            $status = Get-ServiceStatus $svc
            $color = switch ($status) {
                "Running" { "Green" }
                "Stopped" { "Yellow" }
                "Not Installed" { "Red" }
                default { "Gray" }
            }
            Write-Host "  $svc`: " -NoNewline
            Write-Host $status -ForegroundColor $color
        }

        Write-Host ""

        # Check health endpoint if API is running
        $apiStatus = Get-ServiceStatus "pocketwatcher-api"
        if ($apiStatus -eq "Running") {
            Write-Host "Health Check:" -ForegroundColor Cyan
            try {
                $response = Invoke-RestMethod -Uri "http://localhost:8080/api/health" -TimeoutSec 5
                Write-Host "  Status: $($response.status)" -ForegroundColor $(if ($response.status -eq "healthy") { "Green" } else { "Yellow" })
                Write-Host "  Redis: $($response.redis_connected)" -ForegroundColor $(if ($response.redis_connected) { "Green" } else { "Red" })
                Write-Host "  PostgreSQL: $($response.postgres_connected)" -ForegroundColor $(if ($response.postgres_connected) { "Green" } else { "Red" })
                Write-Host "  Stream Active: $($response.stream_active)" -ForegroundColor $(if ($response.stream_active) { "Green" } else { "Yellow" })
            } catch {
                Write-Host "  API not responding" -ForegroundColor Red
            }
        }

        Write-Host ""
    }
}
