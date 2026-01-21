import StatsBar from '../components/StatsBar'
import AlertList from '../components/AlertList'
import { useState, useEffect } from 'react'
import { getHotTokens } from '../api'

function HotTokenCard({ token }) {
  const solscanUrl = `https://solscan.io/token/${token.mint}`

  return (
    <div className="bg-pw-dark rounded-lg p-3 border border-pw-border hover:border-pw-yellow transition-colors">
      <a
        href={solscanUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="text-pw-yellow hover:underline font-mono text-sm truncate block"
      >
        {token.mint.slice(0, 8)}...{token.mint.slice(-4)}
      </a>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
        <div>
          <span className="text-gray-500">Vol:</span>{' '}
          <span className="text-pw-green">{token.buy_volume_sol_5m.toFixed(2)} SOL</span>
        </div>
        <div>
          <span className="text-gray-500">Buys:</span> {token.buy_count_5m}
        </div>
        <div>
          <span className="text-gray-500">Ratio:</span> {token.buy_sell_ratio_5m.toFixed(1)}x
        </div>
        <div>
          <span className="text-gray-500">Buyers:</span> {token.unique_buyers_5m}
        </div>
      </div>
    </div>
  )
}

function HotTokensPanel() {
  const [tokens, setTokens] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function fetch() {
      try {
        const data = await getHotTokens()
        setTokens(data.tokens)
      } catch (e) {
        console.error('Failed to fetch hot tokens:', e)
      } finally {
        setLoading(false)
      }
    }

    fetch()
    const interval = setInterval(fetch, 10000)
    return () => clearInterval(interval)
  }, [])

  if (loading) {
    return (
      <div className="bg-pw-card rounded-lg p-4 border border-pw-border animate-pulse">
        <div className="h-6 bg-pw-border rounded w-1/3 mb-4"></div>
        <div className="grid grid-cols-3 gap-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 bg-pw-border rounded"></div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="bg-pw-card rounded-lg border border-pw-border overflow-hidden">
      <div className="px-4 py-3 border-b border-pw-border flex justify-between items-center">
        <h2 className="text-lg font-semibold">HOT Tokens</h2>
        <span className="text-sm text-pw-yellow">{tokens.length} active</span>
      </div>
      {tokens.length === 0 ? (
        <div className="p-8 text-center text-gray-500">
          No HOT tokens right now. Waiting for triggers...
        </div>
      ) : (
        <div className="p-4 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {tokens.slice(0, 8).map((token) => (
            <HotTokenCard key={token.mint} token={token} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function Dashboard() {
  return (
    <div className="space-y-6">
      <StatsBar />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <AlertList />
        </div>
        <div>
          <HotTokensPanel />
        </div>
      </div>
    </div>
  )
}
