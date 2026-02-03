import { useState, useEffect, useRef } from 'react'

const API_BASE = '/api'

function formatSol(value) {
  if (!value) return '0'
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`
  if (value >= 1) return value.toFixed(2)
  return value.toFixed(4)
}

function formatTime(timestamp) {
  if (!timestamp) return ''
  const date = typeof timestamp === 'number'
    ? new Date(timestamp * 1000)
    : new Date(timestamp)
  return date.toLocaleTimeString()
}

function StatBox({ label, value, color = 'text-white', subtext }) {
  return (
    <div className="bg-pw-card rounded-lg p-4 border border-pw-border">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      {subtext && <div className="text-xs text-gray-500 mt-1">{subtext}</div>}
    </div>
  )
}

function SwapRow({ swap }) {
  const sideColor = swap.side === 'buy' ? 'text-pw-green' : 'text-pw-red'
  const sideIcon = swap.side === 'buy' ? '↑' : '↓'

  return (
    <tr className="border-b border-pw-border hover:bg-pw-card/50">
      <td className="py-2 px-3 text-gray-400 text-xs font-mono">{formatTime(swap.block_time)}</td>
      <td className={`py-2 px-3 font-semibold ${sideColor}`}>{sideIcon} {swap.side.toUpperCase()}</td>
      <td className="py-2 px-3 text-white">{formatSol(swap.amount_sol)} SOL</td>
      <td className="py-2 px-3 text-gray-400 text-xs font-mono">{swap.wallet}</td>
      <td className="py-2 px-3 text-gray-500 text-xs">{swap.venue || '-'}</td>
      <td className="py-2 px-3">
        <a
          href={`https://solscan.io/token/${swap.mint}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-pw-blue hover:underline text-xs font-mono"
        >
          {swap.mint.slice(0, 8)}...
        </a>
      </td>
    </tr>
  )
}

function AlertRow({ alert }) {
  return (
    <div className="bg-pw-card rounded-lg p-3 border border-pw-border hover:border-pw-blue transition-colors">
      <div className="flex justify-between items-start">
        <div>
          <span className="text-pw-yellow font-semibold">
            {alert.token_symbol || alert.token_name || alert.mint.slice(0, 8)}
          </span>
          <span className="text-gray-500 text-xs ml-2">{alert.trigger_name}</span>
        </div>
        <span className="text-gray-500 text-xs">{formatTime(alert.created_at)}</span>
      </div>
      <div className="flex gap-4 mt-1 text-xs text-gray-400">
        <span>Vol: {formatSol(alert.volume_sol_5m)} SOL</span>
        {alert.mcap_sol && <span>MCap: {formatSol(alert.mcap_sol)} SOL</span>}
      </div>
    </div>
  )
}

export default function LiveStream() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [paused, setPaused] = useState(false)
  const intervalRef = useRef(null)

  const fetchData = async () => {
    if (paused) return
    try {
      const res = await fetch(`${API_BASE}/live-stream?limit=100`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
      setLastUpdate(new Date())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => {
    fetchData()
    intervalRef.current = setInterval(fetchData, 2000) // Refresh every 2s
    return () => clearInterval(intervalRef.current)
  }, [paused])

  const stats = data?.stats || {}
  const modeColor = {
    NORMAL: 'text-pw-green',
    DEGRADED: 'text-pw-yellow',
    CRITICAL: 'text-pw-red',
  }

  // Determine mode from lag/stream
  const lag = stats.processing_lag_seconds || 0
  const streamLen = stats.stream_length || 0
  let mode = 'NORMAL'
  if (lag > 30 || streamLen > 80000) mode = 'CRITICAL'
  else if (lag > 5 || streamLen > 50000) mode = 'DEGRADED'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-white">Live Stream</h1>
          <p className="text-gray-500 text-sm">
            Real-time transaction processing
            {lastUpdate && <span> · Updated {lastUpdate.toLocaleTimeString()}</span>}
          </p>
        </div>
        <button
          onClick={() => setPaused(!paused)}
          className={`px-4 py-2 rounded-lg font-semibold ${
            paused
              ? 'bg-pw-green text-white'
              : 'bg-pw-red text-white'
          }`}
        >
          {paused ? '▶ Resume' : '⏸ Pause'}
        </button>
      </div>

      {error && (
        <div className="bg-pw-red/20 border border-pw-red rounded-lg p-4 text-pw-red">
          Failed to load: {error}
        </div>
      )}

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
        <StatBox
          label="TX/s"
          value={stats.tx_per_second?.toFixed(1) || '0'}
          color="text-white"
          subtext={`${(stats.transactions_processed || 0).toLocaleString()} total`}
        />
        <StatBox
          label="Swaps"
          value={(stats.swaps_detected || 0).toLocaleString()}
          color="text-pw-blue"
        />
        <StatBox
          label="HOT Tokens"
          value={stats.hot_tokens_current || 0}
          color="text-pw-yellow"
        />
        <StatBox
          label="Alerts"
          value={stats.alerts_sent || 0}
          color="text-pw-green"
        />
        <StatBox
          label="Stream"
          value={(streamLen).toLocaleString()}
          color={streamLen > 50000 ? 'text-pw-red' : 'text-white'}
          subtext="backlog"
        />
        <StatBox
          label="Lag"
          value={`${lag.toFixed(1)}s`}
          color={lag > 30 ? 'text-pw-red' : lag > 5 ? 'text-pw-yellow' : 'text-pw-green'}
          subtext={<span className={modeColor[mode]}>{mode}</span>}
        />
      </div>

      {/* Two columns: Swaps and Alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Swaps - takes 2 columns */}
        <div className="lg:col-span-2 bg-pw-dark rounded-lg border border-pw-border">
          <div className="p-4 border-b border-pw-border">
            <h2 className="text-lg font-semibold text-white">
              Recent Swaps
              <span className="text-gray-500 text-sm ml-2">Last 5 min</span>
            </h2>
          </div>
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-pw-card sticky top-0">
                <tr className="text-left text-gray-500 text-xs uppercase">
                  <th className="py-2 px-3">Time</th>
                  <th className="py-2 px-3">Side</th>
                  <th className="py-2 px-3">Amount</th>
                  <th className="py-2 px-3">Wallet</th>
                  <th className="py-2 px-3">Venue</th>
                  <th className="py-2 px-3">Token</th>
                </tr>
              </thead>
              <tbody>
                {data?.swaps?.length > 0 ? (
                  data.swaps.map((swap, i) => <SwapRow key={i} swap={swap} />)
                ) : (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-gray-500">
                      {paused ? 'Paused' : 'No recent swaps'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Recent Alerts & HOT Tokens */}
        <div className="space-y-6">
          {/* Recent Alerts */}
          <div className="bg-pw-dark rounded-lg border border-pw-border">
            <div className="p-4 border-b border-pw-border">
              <h2 className="text-lg font-semibold text-white">
                Recent Alerts
                <span className="text-gray-500 text-sm ml-2">Last hour</span>
              </h2>
            </div>
            <div className="p-4 space-y-2 max-h-48 overflow-y-auto">
              {data?.alerts?.length > 0 ? (
                data.alerts.map((alert) => <AlertRow key={alert.id} alert={alert} />)
              ) : (
                <div className="text-center text-gray-500 py-4">No recent alerts</div>
              )}
            </div>
          </div>

          {/* HOT Tokens */}
          <div className="bg-pw-dark rounded-lg border border-pw-border">
            <div className="p-4 border-b border-pw-border">
              <h2 className="text-lg font-semibold text-white">
                HOT Tokens
                <span className="text-pw-yellow text-sm ml-2">
                  {data?.hot_tokens?.length || 0} active
                </span>
              </h2>
            </div>
            <div className="p-4 max-h-48 overflow-y-auto">
              {data?.hot_tokens?.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {data.hot_tokens.map((mint) => (
                    <a
                      key={mint}
                      href={`https://solscan.io/token/${mint}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="bg-pw-card px-2 py-1 rounded text-xs font-mono text-pw-yellow hover:bg-pw-yellow/20"
                    >
                      {mint.slice(0, 8)}...
                    </a>
                  ))}
                </div>
              ) : (
                <div className="text-center text-gray-500 py-4">No HOT tokens</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
