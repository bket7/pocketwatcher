import { useState, useEffect } from 'react'
import { getAlerts } from '../api'

function AlertRow({ alert }) {
  const solscanUrl = `https://solscan.io/token/${alert.mint}`

  return (
    <tr className="border-b border-pw-border hover:bg-pw-dark/50 transition-colors">
      <td className="px-4 py-3">
        <div className="flex flex-col">
          <a
            href={solscanUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-pw-blue hover:underline font-medium"
          >
            {alert.token_symbol || alert.mint.slice(0, 8)}
          </a>
          <span className="text-xs text-gray-500">{alert.token_name}</span>
        </div>
      </td>
      <td className="px-4 py-3">
        <span className="px-2 py-1 bg-pw-dark rounded text-sm">
          {alert.trigger_name}
        </span>
      </td>
      <td className="px-4 py-3 text-right">
        <span className="text-pw-green">{alert.volume_sol_5m.toFixed(2)} SOL</span>
      </td>
      <td className="px-4 py-3 text-right">{alert.buy_count_5m}</td>
      <td className="px-4 py-3 text-right">{alert.unique_buyers_5m}</td>
      <td className="px-4 py-3 text-right">
        <span className={alert.buy_sell_ratio_5m > 5 ? 'text-pw-green' : ''}>
          {alert.buy_sell_ratio_5m.toFixed(1)}x
        </span>
      </td>
      <td className="px-4 py-3 text-gray-500 text-sm">
        {new Date(alert.created_at).toLocaleTimeString()}
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
                <th className="px-4 py-2">Trigger</th>
                <th className="px-4 py-2 text-right">Volume</th>
                <th className="px-4 py-2 text-right">Buys</th>
                <th className="px-4 py-2 text-right">Buyers</th>
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
