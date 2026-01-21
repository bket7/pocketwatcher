import { useState, useEffect } from 'react'
import { getStats, getHealth } from '../api'

function StatCard({ label, value, color = 'text-white' }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-gray-500 uppercase tracking-wider">{label}</span>
      <span className={`text-lg font-semibold ${color}`}>{value}</span>
    </div>
  )
}

function StatusIndicator({ status }) {
  const colors = {
    healthy: 'bg-pw-green',
    degraded: 'bg-pw-yellow',
    unhealthy: 'bg-pw-red',
  }
  const bgColor = colors[status] || 'bg-gray-500'

  return (
    <div className="flex items-center gap-2">
      <span className={`w-2.5 h-2.5 rounded-full ${bgColor} animate-pulse`}></span>
      <span className="text-sm capitalize">{status}</span>
    </div>
  )
}

export default function StatsBar() {
  const [stats, setStats] = useState(null)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    async function fetchData() {
      try {
        const [statsData, healthData] = await Promise.all([
          getStats(),
          getHealth(),
        ])
        setStats(statsData)
        setHealth(healthData)
        setError(null)
      } catch (e) {
        setError(e.message)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 5000) // Refresh every 5s
    return () => clearInterval(interval)
  }, [])

  if (error) {
    return (
      <div className="bg-pw-card rounded-lg p-4 border border-pw-red">
        <span className="text-pw-red">Failed to load stats: {error}</span>
      </div>
    )
  }

  if (!stats || !health) {
    return (
      <div className="bg-pw-card rounded-lg p-4 border border-pw-border animate-pulse">
        <div className="h-6 bg-pw-border rounded w-1/2"></div>
      </div>
    )
  }

  const modeColors = {
    NORMAL: 'text-pw-green',
    DEGRADED: 'text-pw-yellow',
    CRITICAL: 'text-pw-red',
  }

  return (
    <div className="bg-pw-card rounded-lg p-4 border border-pw-border">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-6">
          <StatCard
            label="Tx/s"
            value={stats.tx_per_second.toFixed(1)}
          />
          <StatCard
            label="HOT Tokens"
            value={stats.hot_tokens_current}
            color="text-pw-yellow"
          />
          <StatCard
            label="Alerts Today"
            value={stats.alerts_today}
            color="text-pw-blue"
          />
          <StatCard
            label="Stream"
            value={stats.stream_length.toLocaleString()}
          />
          <StatCard
            label="Lag"
            value={`${stats.processing_lag_seconds.toFixed(1)}s`}
            color={stats.processing_lag_seconds > 5 ? 'text-pw-red' : 'text-white'}
          />
          <StatCard
            label="Mode"
            value={stats.mode}
            color={modeColors[stats.mode]}
          />
        </div>
        <StatusIndicator status={health.status} />
      </div>
    </div>
  )
}
