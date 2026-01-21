import { useState, useEffect } from 'react'
import {
  getSettings,
  updateAlertSettings,
  updateBackpressureSettings,
  updateDetectionSettings,
} from '../api'

function SettingsSection({ title, children, onSave, saving }) {
  return (
    <div className="bg-pw-card rounded-lg border border-pw-border">
      <div className="px-4 py-3 border-b border-pw-border flex justify-between items-center">
        <h3 className="font-semibold">{title}</h3>
        <button
          onClick={onSave}
          disabled={saving}
          className="px-4 py-1.5 bg-pw-green text-white text-sm rounded hover:bg-pw-green/80 disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
      <div className="p-4 space-y-4">{children}</div>
    </div>
  )
}

function InputField({ label, value, onChange, type = 'text', placeholder, help }) {
  return (
    <div>
      <label className="block text-sm text-gray-400 mb-1">{label}</label>
      <input
        type={type}
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-pw-dark border border-pw-border rounded px-3 py-2"
      />
      {help && <p className="text-xs text-gray-500 mt-1">{help}</p>}
    </div>
  )
}

function NumberField({ label, value, onChange, min, max, help }) {
  return (
    <div>
      <label className="block text-sm text-gray-400 mb-1">{label}</label>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value) || 0)}
        min={min}
        max={max}
        className="w-full bg-pw-dark border border-pw-border rounded px-3 py-2"
      />
      {help && <p className="text-xs text-gray-500 mt-1">{help}</p>}
    </div>
  )
}

export default function SettingsPanel() {
  const [settings, setSettings] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState({})
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  // Local state for each section
  const [alerts, setAlerts] = useState({})
  const [backpressure, setBackpressure] = useState({})
  const [detection, setDetection] = useState({})

  useEffect(() => {
    fetchSettings()
  }, [])

  async function fetchSettings() {
    try {
      setLoading(true)
      const data = await getSettings()
      setSettings(data)
      setAlerts(data.alerts)
      setBackpressure(data.backpressure)
      setDetection(data.detection)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleSaveAlerts = async () => {
    try {
      setSaving({ ...saving, alerts: true })
      await updateAlertSettings(alerts)
      showSuccess('Alert settings saved')
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving({ ...saving, alerts: false })
    }
  }

  const handleSaveBackpressure = async () => {
    try {
      setSaving({ ...saving, backpressure: true })
      await updateBackpressureSettings(backpressure)
      showSuccess('Backpressure settings saved')
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving({ ...saving, backpressure: false })
    }
  }

  const handleSaveDetection = async () => {
    try {
      setSaving({ ...saving, detection: true })
      await updateDetectionSettings(detection)
      showSuccess('Detection settings saved')
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving({ ...saving, detection: false })
    }
  }

  const showSuccess = (msg) => {
    setSuccess(msg)
    setTimeout(() => setSuccess(null), 3000)
  }

  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-pw-card rounded-lg p-4 border border-pw-border animate-pulse">
            <div className="h-6 bg-pw-border rounded w-1/3 mb-4"></div>
            <div className="space-y-2">
              <div className="h-10 bg-pw-border rounded"></div>
              <div className="h-10 bg-pw-border rounded"></div>
            </div>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Feedback messages */}
      {error && (
        <div className="bg-pw-red/20 border border-pw-red rounded-lg px-4 py-3 text-pw-red">
          {error}
        </div>
      )}
      {success && (
        <div className="bg-pw-green/20 border border-pw-green rounded-lg px-4 py-3 text-pw-green">
          {success}
        </div>
      )}

      {/* Alert Channels */}
      <SettingsSection
        title="Alert Channels"
        onSave={handleSaveAlerts}
        saving={saving.alerts}
      >
        <InputField
          label="Discord Webhook URL"
          value={alerts.discord_webhook_url}
          onChange={(v) => setAlerts({ ...alerts, discord_webhook_url: v })}
          placeholder="https://discord.com/api/webhooks/..."
          help="Webhook URL for Discord channel alerts"
        />
        <div className="grid grid-cols-2 gap-4">
          <InputField
            label="Telegram Bot Token"
            value={alerts.telegram_bot_token}
            onChange={(v) => setAlerts({ ...alerts, telegram_bot_token: v })}
            placeholder="123456:ABC-DEF..."
            help="Bot token from @BotFather"
          />
          <InputField
            label="Telegram Chat ID"
            value={alerts.telegram_chat_id}
            onChange={(v) => setAlerts({ ...alerts, telegram_chat_id: v })}
            placeholder="-100123456789"
            help="Group or channel chat ID"
          />
        </div>
      </SettingsSection>

      {/* Backpressure */}
      <SettingsSection
        title="Backpressure Thresholds"
        onSave={handleSaveBackpressure}
        saving={saving.backpressure}
      >
        <div className="grid grid-cols-2 gap-4">
          <NumberField
            label="Degraded Lag (seconds)"
            value={backpressure.degraded_lag_seconds}
            onChange={(v) => setBackpressure({ ...backpressure, degraded_lag_seconds: v })}
            min={1}
            max={60}
            help="Processing lag to trigger DEGRADED mode"
          />
          <NumberField
            label="Critical Lag (seconds)"
            value={backpressure.critical_lag_seconds}
            onChange={(v) => setBackpressure({ ...backpressure, critical_lag_seconds: v })}
            min={5}
            max={120}
            help="Processing lag to trigger CRITICAL mode"
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <NumberField
            label="Degraded Stream Length"
            value={backpressure.degraded_stream_len}
            onChange={(v) => setBackpressure({ ...backpressure, degraded_stream_len: v })}
            min={1000}
            max={100000}
            help="Stream buffer size for DEGRADED mode"
          />
          <NumberField
            label="Critical Stream Length"
            value={backpressure.critical_stream_len}
            onChange={(v) => setBackpressure({ ...backpressure, critical_stream_len: v })}
            min={5000}
            max={200000}
            help="Stream buffer size for CRITICAL mode"
          />
        </div>
      </SettingsSection>

      {/* Detection */}
      <SettingsSection
        title="Detection Parameters"
        onSave={handleSaveDetection}
        saving={saving.detection}
      >
        <div className="grid grid-cols-3 gap-4">
          <NumberField
            label="HOT Token TTL (seconds)"
            value={detection.hot_token_ttl_seconds}
            onChange={(v) => setDetection({ ...detection, hot_token_ttl_seconds: v })}
            min={300}
            max={7200}
            help="How long tokens stay HOT"
          />
          <NumberField
            label="Alert Cooldown (seconds)"
            value={detection.alert_cooldown_seconds}
            onChange={(v) => setDetection({ ...detection, alert_cooldown_seconds: v })}
            min={60}
            max={3600}
            help="Min time between alerts for same token"
          />
          <div>
            <label className="block text-sm text-gray-400 mb-1">Min Swap Confidence</label>
            <input
              type="number"
              value={detection.min_swap_confidence}
              onChange={(e) =>
                setDetection({ ...detection, min_swap_confidence: parseFloat(e.target.value) || 0 })
              }
              min={0}
              max={1}
              step={0.1}
              className="w-full bg-pw-dark border border-pw-border rounded px-3 py-2"
            />
            <p className="text-xs text-gray-500 mt-1">Threshold for swap detection (0-1)</p>
          </div>
        </div>
      </SettingsSection>

      {/* Info about non-hot-reloadable settings */}
      <div className="bg-pw-card rounded-lg border border-pw-border p-4">
        <h3 className="font-semibold text-gray-400 mb-2">Requires Restart</h3>
        <p className="text-sm text-gray-500">
          The following settings require a restart to take effect and cannot be changed here:
        </p>
        <ul className="text-sm text-gray-500 mt-2 list-disc list-inside">
          <li>Redis URL</li>
          <li>PostgreSQL URL</li>
          <li>Yellowstone endpoint and token</li>
          <li>Helius API key</li>
        </ul>
      </div>
    </div>
  )
}
