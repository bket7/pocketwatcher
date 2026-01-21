import { useState, useEffect } from 'react'
import { getTriggers, updateTriggers, validateTriggers, resetTriggers } from '../api'
import TriggerCard from './TriggerCard'

export default function TriggerEditor() {
  const [triggers, setTriggers] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)
  const [hasChanges, setHasChanges] = useState(false)
  const [newTriggerName, setNewTriggerName] = useState('')
  const [showNewForm, setShowNewForm] = useState(false)

  useEffect(() => {
    fetchTriggers()
  }, [])

  async function fetchTriggers() {
    try {
      setLoading(true)
      const data = await getTriggers()
      setTriggers(data.triggers)
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleUpdateTrigger = (updated) => {
    setTriggers(triggers.map((t) => (t.name === updated.name ? updated : t)))
    setHasChanges(true)
  }

  const handleDeleteTrigger = (name) => {
    if (confirm(`Delete trigger "${name}"?`)) {
      setTriggers(triggers.filter((t) => t.name !== name))
      setHasChanges(true)
    }
  }

  const handleAddTrigger = () => {
    if (!newTriggerName.trim()) return

    const name = newTriggerName.trim().toLowerCase().replace(/\s+/g, '_')
    if (triggers.some((t) => t.name === name)) {
      setError(`Trigger "${name}" already exists`)
      return
    }

    setTriggers([
      ...triggers,
      {
        name,
        conditions: ['buy_count_5m >= 10'],
        enabled: true,
      },
    ])
    setNewTriggerName('')
    setShowNewForm(false)
    setHasChanges(true)
  }

  const handleSave = async () => {
    try {
      setSaving(true)
      setError(null)

      // Validate first
      const validation = await validateTriggers(triggers)
      if (!validation.valid) {
        setError(validation.errors.join(', '))
        return
      }

      // Save
      await updateTriggers(triggers)
      setSuccess('Triggers saved and hot-reloaded!')
      setHasChanges(false)
      setTimeout(() => setSuccess(null), 3000)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    if (!confirm('Reset triggers to file defaults? This will discard Redis overrides.')) {
      return
    }

    try {
      setSaving(true)
      const data = await resetTriggers()
      setTriggers(data.triggers)
      setSuccess('Triggers reset to defaults')
      setHasChanges(false)
      setTimeout(() => setSuccess(null), 3000)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-pw-card rounded-lg p-4 border border-pw-border animate-pulse">
            <div className="h-6 bg-pw-border rounded w-1/3"></div>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowNewForm(!showNewForm)}
            className="px-4 py-2 bg-pw-blue text-white rounded hover:bg-pw-blue/80"
          >
            + Add Trigger
          </button>
          <button
            onClick={handleReset}
            className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-500"
          >
            Reset to Defaults
          </button>
        </div>
        <button
          onClick={handleSave}
          disabled={!hasChanges || saving}
          className={`px-6 py-2 rounded font-medium transition-colors ${
            hasChanges
              ? 'bg-pw-green text-white hover:bg-pw-green/80'
              : 'bg-gray-600 text-gray-400 cursor-not-allowed'
          }`}
        >
          {saving ? 'Saving...' : 'Save All'}
        </button>
      </div>

      {/* New trigger form */}
      {showNewForm && (
        <div className="bg-pw-card rounded-lg p-4 border border-pw-blue">
          <div className="flex gap-2">
            <input
              type="text"
              value={newTriggerName}
              onChange={(e) => setNewTriggerName(e.target.value)}
              placeholder="Trigger name (e.g., whale_activity)"
              className="flex-1 bg-pw-dark border border-pw-border rounded px-3 py-2"
              onKeyDown={(e) => e.key === 'Enter' && handleAddTrigger()}
            />
            <button
              onClick={handleAddTrigger}
              className="px-4 py-2 bg-pw-blue text-white rounded hover:bg-pw-blue/80"
            >
              Create
            </button>
            <button
              onClick={() => setShowNewForm(false)}
              className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-500"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

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

      {/* Trigger list */}
      <div className="space-y-3">
        {triggers.map((trigger) => (
          <TriggerCard
            key={trigger.name}
            trigger={trigger}
            onUpdate={handleUpdateTrigger}
            onDelete={handleDeleteTrigger}
          />
        ))}
      </div>

      {triggers.length === 0 && (
        <div className="bg-pw-card rounded-lg p-8 border border-pw-border text-center text-gray-500">
          No triggers configured. Add one to get started.
        </div>
      )}
    </div>
  )
}
