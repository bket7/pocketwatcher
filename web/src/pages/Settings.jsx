import SettingsPanel from '../components/SettingsPanel'
import StatsBar from '../components/StatsBar'

export default function Settings() {
  return (
    <div className="space-y-6">
      <StatsBar />

      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">Settings</h2>
          <p className="text-gray-500 mt-1">
            Configure alert channels and detection parameters. Changes are applied immediately.
          </p>
        </div>
      </div>

      <SettingsPanel />
    </div>
  )
}
