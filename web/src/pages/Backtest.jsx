import { useState, useEffect, useCallback } from 'react'
import { getBacktest, refreshBacktest, getSolPrice } from '../api'

function formatNumber(num, decimals = 0) {
  if (num === null || num === undefined) return '—'
  if (num >= 1_000_000) return `$${(num / 1_000_000).toFixed(1)}M`
  if (num >= 1_000) return `$${(num / 1_000).toFixed(0)}K`
  return `$${num.toFixed(decimals)}`
}

function formatPercent(pct) {
  if (pct === null || pct === undefined) return '—'
  const sign = pct >= 0 ? '+' : ''
  return `${sign}${pct.toFixed(0)}%`
}

function StatusBadge({ status }) {
  const styles = {
    winner: 'bg-green-900/50 text-green-400 border-green-700',
    loser: 'bg-red-900/50 text-red-400 border-red-700',
    dead: 'bg-gray-800/50 text-gray-500 border-gray-700',
  }
  const icons = { winner: '🟢', loser: '🔴', dead: '💀' }

  return (
    <span className={`px-2 py-0.5 rounded border text-xs ${styles[status] || styles.dead}`}>
      {icons[status] || '💀'}
    </span>
  )
}

function WinRateBar({ rate }) {
  if (rate === null || rate === undefined) return <span className="text-gray-500">—</span>

  const pct = Math.round(rate * 100)
  const color = pct >= 60 ? 'bg-green-500' : pct >= 40 ? 'bg-yellow-500' : 'bg-red-500'

  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-2 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm">{pct}%</span>
    </div>
  )
}

function StatCard({ label, value, subtext, color = 'text-white' }) {
  return (
    <div className="bg-pw-card rounded-lg border border-pw-border p-4">
      <div className="text-sm text-gray-400">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${color}`}>{value}</div>
      {subtext && <div className="text-xs text-gray-500 mt-1">{subtext}</div>}
    </div>
  )
}

function TriggerTable({ triggers }) {
  if (!triggers || triggers.length === 0) {
    return <div className="text-gray-500 p-4">No trigger data available</div>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-pw-border text-gray-400 text-left">
            <th className="pb-2 pr-4">Trigger</th>
            <th className="pb-2 pr-4 text-center">Alerts</th>
            <th className="pb-2 pr-4">Win Rate</th>
            <th className="pb-2 pr-4 text-right">Avg Gain</th>
            <th className="pb-2 text-right">Best</th>
          </tr>
        </thead>
        <tbody>
          {triggers.map((t) => (
            <tr key={t.name} className="border-b border-pw-border/50 hover:bg-pw-dark/50">
              <td className="py-2 pr-4 font-mono text-pw-yellow">{t.name}</td>
              <td className="py-2 pr-4 text-center">
                {t.alerts}
                {t.with_price_data < t.alerts && (
                  <span className="text-gray-500 text-xs ml-1">({t.with_price_data})</span>
                )}
              </td>
              <td className="py-2 pr-4">
                <WinRateBar rate={t.win_rate} />
              </td>
              <td className={`py-2 pr-4 text-right ${t.avg_gain_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {formatPercent(t.avg_gain_pct)}
              </td>
              <td className="py-2 text-right text-green-400">{formatPercent(t.best_gain_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ResultsTable({ results, solPrice }) {
  const [filter, setFilter] = useState('all')
  const [sortBy, setSortBy] = useState('gain')

  const filtered = results.filter((r) => {
    if (filter === 'all') return true
    return r.status === filter
  })

  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === 'gain') {
      if (a.status === 'dead' && b.status !== 'dead') return 1
      if (b.status === 'dead' && a.status !== 'dead') return -1
      return (b.gain_pct || -Infinity) - (a.gain_pct || -Infinity)
    }
    if (sortBy === 'age') return a.age_hours - b.age_hours
    return 0
  })

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <div className="flex gap-2">
          {['all', 'winner', 'loser', 'dead'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded text-sm capitalize ${
                filter === f
                  ? 'bg-pw-blue text-white'
                  : 'bg-pw-dark text-gray-400 hover:text-white'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="bg-pw-dark border border-pw-border rounded px-2 py-1 text-sm"
        >
          <option value="gain">Sort by Gain</option>
          <option value="age">Sort by Age</option>
        </select>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-pw-border text-gray-400 text-left">
              <th className="pb-2 pr-4">Token</th>
              <th className="pb-2 pr-4">Trigger</th>
              <th className="pb-2 pr-4 text-right">Alert MC</th>
              <th className="pb-2 pr-4 text-right">Current MC</th>
              <th className="pb-2 pr-4 text-right">Gain</th>
              <th className="pb-2 pr-4 text-center">Status</th>
              <th className="pb-2 text-right">Age</th>
            </tr>
          </thead>
          <tbody>
            {sorted.slice(0, 100).map((r, idx) => (
              <tr key={`${r.mint}-${idx}`} className="border-b border-pw-border/30 hover:bg-pw-dark/50">
                <td className="py-2 pr-4">
                  <div className="flex items-center gap-2">
                    {r.token_image && (
                      <img
                        src={r.token_image}
                        alt=""
                        className="w-5 h-5 rounded-full"
                        onError={(e) => (e.target.style.display = 'none')}
                      />
                    )}
                    <a
                      href={`https://dexscreener.com/solana/${r.mint}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-pw-yellow hover:underline font-mono"
                    >
                      {r.symbol ? `$${r.symbol}` : r.mint.slice(0, 6) + '...'}
                    </a>
                  </div>
                </td>
                <td className="py-2 pr-4 text-gray-400 text-xs">{r.trigger}</td>
                <td className="py-2 pr-4 text-right text-gray-400">{formatNumber(r.alert_mcap_usd)}</td>
                <td className="py-2 pr-4 text-right">{formatNumber(r.current_mcap_usd)}</td>
                <td
                  className={`py-2 pr-4 text-right font-semibold ${
                    r.gain_pct !== null
                      ? r.gain_pct >= 0
                        ? 'text-green-400'
                        : 'text-red-400'
                      : 'text-gray-500'
                  }`}
                >
                  {formatPercent(r.gain_pct)}
                </td>
                <td className="py-2 pr-4 text-center">
                  <StatusBadge status={r.status} />
                </td>
                <td className="py-2 text-right text-gray-400">{r.age_hours}h</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sorted.length > 100 && (
          <div className="text-center text-gray-500 py-2">Showing first 100 of {sorted.length}</div>
        )}
      </div>
    </div>
  )
}

export default function Backtest() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [hours, setHours] = useState(24)
  const [solPrice, setSolPrice] = useState(200)

  const fetchData = useCallback(async () => {
    try {
      setError(null)
      const [backtestData, price] = await Promise.all([getBacktest(hours), getSolPrice()])
      setData(backtestData)
      setSolPrice(price)
    } catch (e) {
      console.error('Failed to fetch backtest:', e)
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [hours])

  useEffect(() => {
    setLoading(true)
    fetchData()
  }, [fetchData])

  const handleRefresh = async () => {
    setRefreshing(true)
    try {
      const result = await refreshBacktest(hours)
      setData(result)
    } catch (e) {
      console.error('Refresh failed:', e)
    } finally {
      setRefreshing(false)
    }
  }

  const timeRanges = [
    { label: '24h', value: 24 },
    { label: '7d', value: 168 },
    { label: '30d', value: 720 },
  ]

  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-8 bg-pw-card rounded w-48" />
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 bg-pw-card rounded" />
          ))}
        </div>
        <div className="h-64 bg-pw-card rounded" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-700 rounded-lg p-4">
        <h2 className="text-red-400 font-bold">Error loading backtest data</h2>
        <p className="text-red-300 mt-2">{error}</p>
        <button
          onClick={fetchData}
          className="mt-4 px-4 py-2 bg-red-700 hover:bg-red-600 rounded"
        >
          Retry
        </button>
      </div>
    )
  }

  const summary = data?.summary || {}
  const triggers = data?.by_trigger || []
  const results = data?.results || []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold">Backtest Results</h1>
        <div className="flex items-center gap-4">
          {/* Time range selector */}
          <div className="flex gap-1 bg-pw-dark rounded-lg p-1">
            {timeRanges.map((range) => (
              <button
                key={range.value}
                onClick={() => setHours(range.value)}
                className={`px-3 py-1 rounded text-sm ${
                  hours === range.value
                    ? 'bg-pw-blue text-white'
                    : 'text-gray-400 hover:text-white'
                }`}
              >
                {range.label}
              </button>
            ))}
          </div>

          {/* Refresh button */}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="px-4 py-2 bg-pw-card border border-pw-border rounded-lg hover:bg-pw-dark disabled:opacity-50 flex items-center gap-2"
          >
            <span className={refreshing ? 'animate-spin' : ''}>🔄</span>
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Cache info */}
      {data?.cache_age_seconds !== null && data?.cache_age_seconds !== undefined && (
        <div className="text-xs text-gray-500">
          Data cached {Math.round(data.cache_age_seconds / 60)} min ago
        </div>
      )}

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Total Alerts" value={summary.total_alerts || 0} subtext={`${summary.with_price_data || 0} with price data`} />
        <StatCard
          label="Win Rate"
          value={summary.win_rate !== null ? `${Math.round(summary.win_rate * 100)}%` : '—'}
          color={summary.win_rate >= 0.5 ? 'text-green-400' : 'text-red-400'}
        />
        <StatCard
          label="Avg Gain"
          value={formatPercent(summary.avg_gain_pct)}
          color={summary.avg_gain_pct >= 0 ? 'text-green-400' : 'text-red-400'}
        />
        <div className="bg-pw-card rounded-lg border border-pw-border p-4">
          <div className="text-sm text-gray-400">Best / Worst</div>
          <div className="mt-1">
            {summary.best && (
              <div className="text-green-400 text-sm">
                ${summary.best.symbol} {formatPercent(summary.best.gain_pct)}
              </div>
            )}
            {summary.worst && (
              <div className="text-red-400 text-sm">
                ${summary.worst.symbol} {formatPercent(summary.worst.gain_pct)}
              </div>
            )}
            {!summary.best && !summary.worst && <div className="text-gray-500">—</div>}
          </div>
          <div className="text-xs text-gray-500 mt-1">{summary.dead_tokens || 0} dead tokens</div>
        </div>
      </div>

      {/* Trigger performance */}
      <div className="bg-pw-card rounded-lg border border-pw-border overflow-hidden">
        <div className="px-4 py-3 border-b border-pw-border">
          <h2 className="text-lg font-semibold">Trigger Performance</h2>
        </div>
        <div className="p-4">
          <TriggerTable triggers={triggers} />
        </div>
      </div>

      {/* Results table */}
      <div className="bg-pw-card rounded-lg border border-pw-border overflow-hidden">
        <div className="px-4 py-3 border-b border-pw-border">
          <h2 className="text-lg font-semibold">All Results</h2>
        </div>
        <div className="p-4">
          <ResultsTable results={results} solPrice={solPrice} />
        </div>
      </div>
    </div>
  )
}
