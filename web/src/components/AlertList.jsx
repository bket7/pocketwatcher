import { useState, useEffect } from 'react'
import { getAlerts } from '../api'

// Format market cap for display
function formatMcap(mcap) {
  if (!mcap || mcap <= 0) return null
  if (mcap >= 1_000_000) return `${(mcap / 1_000_000).toFixed(1)}M`
  if (mcap >= 1_000) return `${(mcap / 1_000).toFixed(1)}K`
  return `${mcap.toFixed(0)}`
}

// Venue badges
const VENUE_BADGES = {
  pump: { emoji: '💧', name: 'pump.fun', color: 'text-green-400' },
  jupiter: { emoji: '💫', name: 'Jupiter', color: 'text-purple-400' },
  raydium: { emoji: '✨', name: 'Raydium', color: 'text-blue-400' },
  orca: { emoji: '🐳', name: 'Orca', color: 'text-cyan-400' },
  meteora: { emoji: '☄️', name: 'Meteora', color: 'text-orange-400' },
}

function AlertRow({ alert }) {
  const dexUrl = `https://dexscreener.com/solana/${alert.mint}`
  const mcapDisplay = formatMcap(alert.mcap_sol)
  const avgEntryDisplay = formatMcap(alert.avg_entry_mcap)
  const venue = VENUE_BADGES[alert.venue] || { emoji: '🔄', name: 'DEX', color: 'text-gray-400' }

  return (
    <tr className="border-b border-pw-border hover:bg-pw-dark/50 transition-colors">
      {/* Token + Venue */}
      <td className="px-4 py-3">
        <div className="flex flex-col">
          <div className="flex items-center gap-2">
            {alert.token_image && (
              <img src={alert.token_image} alt="" className="w-6 h-6 rounded-full" />
            )}
            <a
              href={dexUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-pw-blue hover:underline font-bold text-lg"
            >
              ${alert.token_symbol || alert.mint.slice(0, 6)}
            </a>
            <span className={`text-xs ${venue.color}`} title={venue.name}>
              {venue.emoji}
            </span>
          </div>
          {alert.token_name && alert.token_name !== alert.token_symbol && (
            <span className="text-xs text-gray-500 truncate max-w-[200px]">{alert.token_name}</span>
          )}
        </div>
      </td>

      {/* MCAP AT ALERT - CRITICAL INFO */}
      <td className="px-4 py-3 text-center">
        {mcapDisplay ? (
          <div className="flex flex-col items-center">
            <span className="text-pw-yellow font-bold text-lg">{mcapDisplay}</span>
            <span className="text-xs text-gray-500">SOL mcap</span>
          </div>
        ) : (
          <span className="text-gray-600">—</span>
        )}
      </td>

      {/* AVG ENTRY MCAP - When did buyers start accumulating? */}
      <td className="px-4 py-3 text-center">
        {avgEntryDisplay ? (
          <div className="flex flex-col items-center">
            <span className="text-pw-green font-bold">{avgEntryDisplay}</span>
            <span className="text-xs text-gray-500">avg entry</span>
          </div>
        ) : (
          <span className="text-gray-600">—</span>
        )}
      </td>

      {/* Trigger */}
      <td className="px-4 py-3">
        <span className="px-2 py-1 bg-pw-dark rounded text-xs whitespace-nowrap">
          {alert.trigger_name.replace(/_/g, ' ')}
        </span>
      </td>

      {/* Volume */}
      <td className="px-4 py-3 text-right">
        <span className="text-pw-green font-medium">{alert.volume_sol_5m.toFixed(1)}</span>
        <span className="text-gray-500 text-sm ml-1">SOL</span>
      </td>

      {/* Buyers */}
      <td className="px-4 py-3 text-center">
        <span className="font-medium">{alert.unique_buyers_5m}</span>
        <span className="text-gray-500 text-xs ml-1">/ {alert.buy_count_5m}</span>
      </td>

      {/* Ratio */}
      <td className="px-4 py-3 text-right">
        <span className={alert.buy_sell_ratio_5m > 10 ? 'text-pw-green font-bold' : alert.buy_sell_ratio_5m > 5 ? 'text-pw-yellow' : ''}>
          {alert.buy_sell_ratio_5m >= 999 ? '∞' : `${alert.buy_sell_ratio_5m.toFixed(1)}x`}
        </span>
      </td>

      {/* Time */}
      <td className="px-4 py-3 text-gray-500 text-sm whitespace-nowrap">
        {new Date(alert.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
      </td>
    </tr>
  )
}

export default function AlertList() {
  const [alerts, setAlerts] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    async function fetchAlerts() {
      try {
        setLoading(true)
        const data = await getAlerts(20)
        setAlerts(data.alerts)
        setTotal(data.total)
        setError(null)
      } catch (e) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }

    fetchAlerts()
    const interval = setInterval(fetchAlerts, 10000) // Refresh every 10s
    return () => clearInterval(interval)
  }, [])

  if (loading && alerts.length === 0) {
    return (
      <div className="bg-pw-card rounded-lg p-6 border border-pw-border animate-pulse">
        <div className="h-6 bg-pw-border rounded w-1/3 mb-4"></div>
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-12 bg-pw-border rounded"></div>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-pw-card rounded-lg p-6 border border-pw-red">
        <span className="text-pw-red">Failed to load alerts: {error}</span>
      </div>
    )
  }

  return (
    <div className="bg-pw-card rounded-lg border border-pw-border overflow-hidden">
      <div className="px-4 py-3 border-b border-pw-border flex justify-between items-center">
        <h2 className="text-lg font-semibold">Recent Alerts</h2>
        <span className="text-sm text-gray-500">{total} total</span>
      </div>
      {alerts.length === 0 ? (
        <div className="p-8 text-center text-gray-500">
          No alerts yet. Waiting for triggers to fire...
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-pw-dark/50">
              <tr className="text-left text-xs text-gray-500 uppercase tracking-wider">
                <th className="px-4 py-2">Token</th>
                <th className="px-4 py-2 text-center">📊 MCAP</th>
                <th className="px-4 py-2 text-center">🎯 Entry</th>
                <th className="px-4 py-2">Trigger</th>
                <th className="px-4 py-2 text-right">Volume</th>
                <th className="px-4 py-2 text-center">Buyers</th>
                <th className="px-4 py-2 text-right">Ratio</th>
                <th className="px-4 py-2">Time</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((alert) => (
                <AlertRow key={alert.id} alert={alert} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
