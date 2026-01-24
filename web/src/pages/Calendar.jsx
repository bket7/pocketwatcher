import { useState, useEffect } from 'react'
import { getAlertsByDate, getSolPrice } from '../api'

function formatMcapUsd(mcapSol, solPrice) {
  if (!mcapSol || mcapSol <= 0 || !solPrice) return null
  const mcapUsd = mcapSol * solPrice
  if (mcapUsd >= 1_000_000) return `$${(mcapUsd / 1_000_000).toFixed(1)}M`
  if (mcapUsd >= 1_000) return `$${(mcapUsd / 1_000).toFixed(0)}K`
  return `$${mcapUsd.toFixed(0)}`
}

function formatTime(isoString) {
  if (!isoString) return ''
  const date = new Date(isoString)
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
}

function DayCard({ day, solPrice, isSelected, onClick }) {
  const date = new Date(day.date)
  const dayNum = date.getDate()
  const dayName = date.toLocaleDateString('en-US', { weekday: 'short' })
  const monthName = date.toLocaleDateString('en-US', { month: 'short' })

  // Color based on alert count
  let bgColor = 'bg-pw-card'
  if (day.alert_count > 50) bgColor = 'bg-red-900/50'
  else if (day.alert_count > 20) bgColor = 'bg-orange-900/50'
  else if (day.alert_count > 10) bgColor = 'bg-yellow-900/50'
  else if (day.alert_count > 0) bgColor = 'bg-green-900/50'

  return (
    <div
      className={`${bgColor} ${isSelected ? 'ring-2 ring-pw-blue' : ''} rounded-lg p-3 cursor-pointer hover:ring-2 hover:ring-pw-blue/50 transition-all`}
      onClick={onClick}
    >
      <div className="text-xs text-gray-500">{dayName} {monthName}</div>
      <div className="text-2xl font-bold text-white">{dayNum}</div>
      <div className="mt-2 space-y-1">
        <div className="text-lg font-semibold text-pw-blue">{day.alert_count} alerts</div>
        <div className="text-xs text-gray-400">{day.unique_tokens} tokens</div>
      </div>
    </div>
  )
}

function AlertRow({ alert, solPrice }) {
  const mcap = formatMcapUsd(alert.mcap_sol, solPrice)

  return (
    <a
      href={`https://solscan.io/token/${alert.mint}`}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-4 p-3 bg-pw-dark rounded-lg hover:bg-pw-card transition-colors"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-white truncate">
            {alert.token_symbol || alert.token_name || alert.mint.slice(0, 8)}
          </span>
          {mcap && (
            <span className="text-sm text-green-400 font-medium">{mcap}</span>
          )}
        </div>
        <div className="text-sm text-gray-400">{alert.trigger_name}</div>
      </div>
      <div className="text-xs text-gray-500">
        {formatTime(alert.created_at)}
      </div>
    </a>
  )
}

export default function Calendar() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedDate, setSelectedDate] = useState(null)
  const [solPrice, setSolPrice] = useState(null)
  const [days, setDays] = useState(30)

  useEffect(() => {
    loadData()
    loadSolPrice()
  }, [days])

  async function loadData() {
    setLoading(true)
    setError(null)
    try {
      const result = await getAlertsByDate(days)
      setData(result)
      // Auto-select the most recent day with alerts
      if (result.days && result.days.length > 0) {
        setSelectedDate(result.days[0].date)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function loadSolPrice() {
    const price = await getSolPrice()
    setSolPrice(price)
  }

  const selectedDay = data?.days?.find(d => d.date === selectedDate)

  // Calculate summary stats
  const totalAlerts = data?.days?.reduce((sum, d) => sum + d.alert_count, 0) || 0
  const totalTokens = data?.days?.reduce((sum, d) => sum + d.unique_tokens, 0) || 0
  const activeDays = data?.days?.length || 0

  return (
    <div className="space-y-6">
      {/* Header with stats */}
      <div className="bg-pw-card rounded-xl p-6 border border-pw-border">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl font-bold text-white">Alert Calendar</h1>
          <div className="flex gap-2">
            {[7, 14, 30, 60].map(d => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-3 py-1 rounded text-sm ${
                  days === d
                    ? 'bg-pw-blue text-white'
                    : 'bg-pw-dark text-gray-400 hover:text-white'
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>

        {/* Summary stats */}
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-pw-dark rounded-lg p-4 text-center">
            <div className="text-3xl font-bold text-pw-blue">{totalAlerts}</div>
            <div className="text-sm text-gray-400">Total Alerts</div>
          </div>
          <div className="bg-pw-dark rounded-lg p-4 text-center">
            <div className="text-3xl font-bold text-green-400">{totalTokens}</div>
            <div className="text-sm text-gray-400">Tokens Flagged</div>
          </div>
          <div className="bg-pw-dark rounded-lg p-4 text-center">
            <div className="text-3xl font-bold text-yellow-400">{activeDays}</div>
            <div className="text-sm text-gray-400">Active Days</div>
          </div>
        </div>
      </div>

      {loading && (
        <div className="text-center py-12 text-gray-400">Loading calendar data...</div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-500 rounded-lg p-4 text-red-400">
          Error: {error}
        </div>
      )}

      {!loading && !error && data && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Calendar grid */}
          <div className="lg:col-span-2 bg-pw-card rounded-xl p-4 border border-pw-border">
            <h2 className="text-lg font-semibold text-white mb-4">Select a Day</h2>
            <div className="grid grid-cols-7 gap-2">
              {data.days.map(day => (
                <DayCard
                  key={day.date}
                  day={day}
                  solPrice={solPrice}
                  isSelected={day.date === selectedDate}
                  onClick={() => setSelectedDate(day.date)}
                />
              ))}
            </div>
            {data.days.length === 0 && (
              <div className="text-center py-8 text-gray-500">
                No alerts in the last {days} days
              </div>
            )}
          </div>

          {/* Selected day details */}
          <div className="bg-pw-card rounded-xl p-4 border border-pw-border">
            <h2 className="text-lg font-semibold text-white mb-4">
              {selectedDay ? (
                <>
                  {new Date(selectedDay.date).toLocaleDateString('en-US', {
                    weekday: 'long',
                    month: 'long',
                    day: 'numeric'
                  })}
                  <span className="text-sm font-normal text-gray-400 ml-2">
                    ({selectedDay.alert_count} alerts)
                  </span>
                </>
              ) : (
                'Select a day'
              )}
            </h2>

            <div className="space-y-2 max-h-[600px] overflow-y-auto">
              {selectedDay?.alerts?.map(alert => (
                <AlertRow key={alert.id} alert={alert} solPrice={solPrice} />
              ))}
              {!selectedDay && (
                <div className="text-center py-8 text-gray-500">
                  Click a day to see alerts
                </div>
              )}
              {selectedDay && selectedDay.alerts.length === 0 && (
                <div className="text-center py-8 text-gray-500">
                  No alerts on this day
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
