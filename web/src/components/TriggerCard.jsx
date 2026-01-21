import { useState } from 'react'

export default function TriggerCard({ trigger, onUpdate, onDelete }) {
  const [expanded, setExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [localConditions, setLocalConditions] = useState(trigger.conditions)
  const [newCondition, setNewCondition] = useState('')

  const handleToggleEnabled = () => {
    onUpdate({ ...trigger, enabled: !trigger.enabled })
  }

  const handleSaveConditions = () => {
    onUpdate({ ...trigger, conditions: localConditions })
    setEditing(false)
  }

  const handleAddCondition = () => {
    if (newCondition.trim()) {
      setLocalConditions([...localConditions, newCondition.trim()])
      setNewCondition('')
    }
  }

  const handleRemoveCondition = (index) => {
    setLocalConditions(localConditions.filter((_, i) => i !== index))
  }

  const handleConditionChange = (index, value) => {
    const updated = [...localConditions]
    updated[index] = value
    setLocalConditions(updated)
  }

  return (
    <div className={`trigger-card bg-pw-card rounded-lg border ${
      trigger.enabled ? 'border-pw-border' : 'border-pw-border/50 opacity-60'
    }`}>
      {/* Header */}
      <div
        className="px-4 py-3 flex items-center justify-between cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <span className="text-gray-400">{expanded ? '▼' : '▶'}</span>
          <span className="font-medium">{trigger.name}</span>
          <span className="text-xs text-gray-500">
            {trigger.conditions.length} condition{trigger.conditions.length !== 1 ? 's' : ''}
          </span>
        </div>
        <div className="flex items-center gap-3" onClick={(e) => e.stopPropagation()}>
          <button
            className={`px-3 py-1 rounded text-sm transition-colors ${
              trigger.enabled
                ? 'bg-pw-green/20 text-pw-green'
                : 'bg-gray-600/20 text-gray-400'
            }`}
            onClick={handleToggleEnabled}
          >
            {trigger.enabled ? 'Enabled' : 'Disabled'}
          </button>
        </div>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-pw-border">
          <div className="pt-3 space-y-2">
            {editing ? (
              <>
                {localConditions.map((cond, i) => (
                  <div key={i} className="flex gap-2">
                    <input
                      type="text"
                      value={cond}
                      onChange={(e) => handleConditionChange(i, e.target.value)}
                      className="flex-1 bg-pw-dark border border-pw-border rounded px-3 py-2 text-sm font-mono"
                    />
                    <button
                      onClick={() => handleRemoveCondition(i)}
                      className="px-3 py-2 text-pw-red hover:bg-pw-red/10 rounded"
                    >
                      ×
                    </button>
                  </div>
                ))}
                <div className="flex gap-2 mt-3">
                  <input
                    type="text"
                    value={newCondition}
                    onChange={(e) => setNewCondition(e.target.value)}
                    placeholder="e.g., buy_count_5m >= 20"
                    className="flex-1 bg-pw-dark border border-pw-border rounded px-3 py-2 text-sm font-mono"
                    onKeyDown={(e) => e.key === 'Enter' && handleAddCondition()}
                  />
                  <button
                    onClick={handleAddCondition}
                    className="px-3 py-2 bg-pw-blue/20 text-pw-blue rounded hover:bg-pw-blue/30"
                  >
                    Add
                  </button>
                </div>
                <div className="flex gap-2 mt-4">
                  <button
                    onClick={handleSaveConditions}
                    className="px-4 py-2 bg-pw-green text-white rounded hover:bg-pw-green/80"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => {
                      setLocalConditions(trigger.conditions)
                      setEditing(false)
                    }}
                    className="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-500"
                  >
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <>
                {trigger.conditions.map((cond, i) => (
                  <div
                    key={i}
                    className="px-3 py-2 bg-pw-dark rounded font-mono text-sm text-gray-300"
                  >
                    {cond}
                  </div>
                ))}
                <div className="flex gap-2 mt-4">
                  <button
                    onClick={() => setEditing(true)}
                    className="px-4 py-2 bg-pw-blue/20 text-pw-blue rounded hover:bg-pw-blue/30"
                  >
                    Edit Conditions
                  </button>
                  <button
                    onClick={() => onDelete(trigger.name)}
                    className="px-4 py-2 bg-pw-red/20 text-pw-red rounded hover:bg-pw-red/30"
                  >
                    Delete Trigger
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
