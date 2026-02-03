# Pocketwatcher Production Runbook

Operations guide for running Pocketwatcher on a Windows VPS.

## Prerequisites

- Windows Server 2019+ or Windows 10/11
- Python 3.11+
- Node.js 20 LTS
- PostgreSQL 16+
- Redis (Memurai or WSL-based)
- NSSM (Non-Sucking Service Manager)

## Directory Structure

```
C:\pocketwatcher\
├── app\                 # Application code
├── data\
│   ├── logs\           # Application logs
│   └── backups\        # Database backups
├── .env                 # Environment configuration
└── config\
    └── thresholds.yaml  # Trigger configuration
```

## Environment Configuration

Copy `.env.example` to `.env` and configure:

```env
# Required
YELLOWSTONE_ENDPOINT=your-endpoint.chainstack.com:443
YELLOWSTONE_TOKEN=your-token
POSTGRES_URL=postgresql://pocketwatcher:password@localhost:5432/pocketwatcher
HELIUS_API_KEY=your-helius-key

# Optional but recommended
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
API_HOST=127.0.0.1
API_PORT=8080
API_TOKEN=your-secret-token
```

## Starting Services

### Manual Start (Development/Testing)

```powershell
# Terminal 1: Start the main worker
cd C:\pocketwatcher\app
python main.py

# Terminal 2: Start the API server
cd C:\pocketwatcher\app
python -m api.server
```

### Service Start (Production)

Using NSSM for Windows service management:

```powershell
# Install services (one-time setup)
nssm install pocketwatcher-worker "C:\Python311\python.exe" "C:\pocketwatcher\app\main.py"
nssm set pocketwatcher-worker AppDirectory "C:\pocketwatcher\app"
nssm set pocketwatcher-worker AppStdout "C:\pocketwatcher\data\logs\worker.log"
nssm set pocketwatcher-worker AppStderr "C:\pocketwatcher\data\logs\worker-error.log"
nssm set pocketwatcher-worker AppRotateFiles 1
nssm set pocketwatcher-worker AppRotateBytes 10485760

nssm install pocketwatcher-api "C:\Python311\python.exe" "-m" "api.server"
nssm set pocketwatcher-api AppDirectory "C:\pocketwatcher\app"
nssm set pocketwatcher-api AppStdout "C:\pocketwatcher\data\logs\api.log"
nssm set pocketwatcher-api AppStderr "C:\pocketwatcher\data\logs\api-error.log"
nssm set pocketwatcher-api AppRotateFiles 1
nssm set pocketwatcher-api AppRotateBytes 10485760

# Start services
nssm start pocketwatcher-worker
nssm start pocketwatcher-api
```

## Stopping Services

### Graceful Shutdown

```powershell
# Stop via NSSM
nssm stop pocketwatcher-worker
nssm stop pocketwatcher-api
```

The worker handles SIGTERM/SIGINT gracefully:
1. Stops accepting new transactions from Yellowstone
2. Finishes processing current batch
3. Flushes pending alerts
4. Disconnects from Redis/PostgreSQL

### Force Stop (Emergency)

```powershell
# Force stop if graceful shutdown hangs
nssm stop pocketwatcher-worker confirm
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *pocketwatcher*"
```

## Health Checks

### API Health Endpoint

```powershell
# Check service health
Invoke-RestMethod http://localhost:8080/api/health
```

Expected healthy response:
```json
{
  "status": "healthy",
  "redis_connected": true,
  "postgres_connected": true,
  "stream_active": true
}
```

### Manual Health Checks

```powershell
# Check Redis
redis-cli ping

# Check PostgreSQL
psql -U pocketwatcher -d pocketwatcher -c "SELECT 1"

# Check stream backlog
redis-cli XLEN pocketwatcher:ingest

# Check recent alerts
psql -U pocketwatcher -d pocketwatcher -c "SELECT COUNT(*) FROM alerts WHERE created_at > NOW() - INTERVAL '1 hour'"
```

## Backup Procedures

### PostgreSQL Backup

```powershell
# Daily backup script
$date = Get-Date -Format "yyyyMMdd"
$backupPath = "C:\pocketwatcher\data\backups\pg_backup_$date.sql"

pg_dump -U pocketwatcher -d pocketwatcher -F c -f $backupPath

# Compress
Compress-Archive -Path $backupPath -DestinationPath "$backupPath.zip"
Remove-Item $backupPath

# Keep last 7 days
Get-ChildItem "C:\pocketwatcher\data\backups\pg_backup_*.zip" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item
```

### Redis Backup

```powershell
# Trigger RDB snapshot
redis-cli BGSAVE

# Wait for completion
redis-cli LASTSAVE

# Copy snapshot
$date = Get-Date -Format "yyyyMMdd"
Copy-Item "C:\Redis\dump.rdb" "C:\pocketwatcher\data\backups\redis_$date.rdb"
```

### Automated Backup (Task Scheduler)

Create `backup.ps1`:
```powershell
$date = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = "C:\pocketwatcher\data\backups"

# PostgreSQL
pg_dump -U pocketwatcher -d pocketwatcher -F c -f "$backupDir\pg_$date.dump"

# Redis
redis-cli BGSAVE
Start-Sleep -Seconds 5
Copy-Item "C:\Redis\dump.rdb" "$backupDir\redis_$date.rdb"

# Cleanup old backups (keep 7 days)
Get-ChildItem "$backupDir\*" -Include "pg_*.dump","redis_*.rdb" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item

Write-Host "Backup completed: $date"
```

Schedule with Task Scheduler to run daily.

## Restore Procedures

### PostgreSQL Restore

```powershell
# Stop services first
nssm stop pocketwatcher-worker
nssm stop pocketwatcher-api

# Restore from backup
pg_restore -U pocketwatcher -d pocketwatcher -c "C:\pocketwatcher\data\backups\pg_backup_20260201.dump"

# Restart services
nssm start pocketwatcher-worker
nssm start pocketwatcher-api
```

### Redis Restore

```powershell
# Stop Redis
net stop Redis

# Replace dump.rdb
Copy-Item "C:\pocketwatcher\data\backups\redis_20260201.rdb" "C:\Redis\dump.rdb"

# Start Redis
net start Redis
```

## Troubleshooting

### High Processing Lag

**Symptoms**: `/api/stats` shows `processing_lag_seconds` > 30

**Causes**:
1. Yellowstone connection issues
2. Database bottleneck
3. Insufficient consumer count

**Solutions**:
```powershell
# Check stream length
redis-cli XLEN pocketwatcher:ingest

# Increase consumer count (edit .env)
STREAM_CONSUMER_COUNT=2

# Restart worker
nssm restart pocketwatcher-worker
```

### No Alerts Firing

**Symptoms**: Dashboard shows 0 alerts but HOT tokens exist

**Causes**:
1. Triggers too strict
2. Discord webhook invalid
3. Alert cooldown active

**Solutions**:
```powershell
# Check trigger config
cat C:\pocketwatcher\app\config\thresholds.yaml

# Test Discord webhook
curl -X POST -H "Content-Type: application/json" -d '{"content":"test"}' $DISCORD_WEBHOOK_URL

# Check recent trigger evaluations in logs
Get-Content C:\pocketwatcher\data\logs\worker.log | Select-String "trigger" | Select-Object -Last 20
```

### Connection Errors

**Redis connection refused**:
```powershell
# Check Redis is running
Get-Service Redis
net start Redis
```

**PostgreSQL connection refused**:
```powershell
# Check PostgreSQL is running
Get-Service postgresql*
net start postgresql-x64-16
```

### Worker Crashes

**Check error logs**:
```powershell
Get-Content C:\pocketwatcher\data\logs\worker-error.log -Tail 100
```

**Common issues**:
- Out of memory: Increase `REDIS_STREAM_MAXLEN`
- gRPC timeout: Check Chainstack endpoint status
- Database pool exhausted: Restart PostgreSQL

## Metrics and Monitoring

### Prometheus Endpoint

```
http://localhost:8080/metrics
```

Key metrics:
- `pocketwatcher_tx_processed_total` - Transactions processed
- `pocketwatcher_swaps_detected_total` - Swaps detected
- `pocketwatcher_alerts_sent_total` - Alerts sent
- `pocketwatcher_stream_length` - Current stream backlog
- `pocketwatcher_processing_lag_seconds` - Processing delay

### Log Files

| Log | Location | Contains |
|-----|----------|----------|
| Worker | `data/logs/worker.log` | Transaction processing, alerts |
| API | `data/logs/api.log` | API requests, config changes |
| Worker Errors | `data/logs/worker-error.log` | Exceptions, crashes |

### Log Rotation

NSSM handles log rotation via AppRotateFiles. Manual rotation:
```powershell
# Archive old logs
$date = Get-Date -Format "yyyyMMdd"
Compress-Archive -Path "C:\pocketwatcher\data\logs\*.log" -DestinationPath "C:\pocketwatcher\data\logs\archive_$date.zip"
Get-ChildItem "C:\pocketwatcher\data\logs\*.log" | Remove-Item
```

## Configuration Changes

### Hot-Reload (No Restart)

These settings can be changed via the dashboard or API without restart:
- Trigger thresholds (`PUT /api/triggers`)
- Alert channel settings (`PUT /api/settings`)
- Detection parameters (`PUT /api/settings`)

### Requires Restart

These changes require service restart:
- Environment variables (`.env`)
- Database URLs
- Yellowstone credentials

```powershell
nssm restart pocketwatcher-worker
nssm restart pocketwatcher-api
```

## Emergency Procedures

### Complete Shutdown

```powershell
nssm stop pocketwatcher-worker
nssm stop pocketwatcher-api
net stop Redis
net stop postgresql-x64-16
```

### Complete Startup

```powershell
net start postgresql-x64-16
net start Redis
nssm start pocketwatcher-api
nssm start pocketwatcher-worker
```

### Clear Stream Backlog (Data Loss)

Only use if backlog is unrecoverable:
```powershell
redis-cli DEL pocketwatcher:ingest
```
