import TriggerEditor from '../components/TriggerEditor'
import StatsBar from '../components/StatsBar'

export default function Triggers() {
  return (
    <div className="space-y-6">
      <StatsBar />

      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">Trigger Configuration</h2>
          <p className="text-gray-500 mt-1">
            Configure detection triggers. Changes are hot-reloaded instantly.
          </p>
        </div>
      </div>

      <TriggerEditor />

      {/* Help section */}
      <div className="bg-pw-card rounded-lg border border-pw-border p-4">
        <h3 className="font-semibold mb-3">Available Stats Fields</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
          <div>
            <h4 className="text-gray-400 mb-2">5-Minute Window</h4>
            <ul className="space-y-1 text-gray-500 font-mono text-xs">
              <li>buy_count_5m</li>
              <li>sell_count_5m</li>
              <li>unique_buyers_5m</li>
              <li>unique_sellers_5m</li>
              <li>buy_volume_sol_5m</li>
              <li>avg_buy_size_5m</li>
              <li>buy_sell_ratio_5m</li>
              <li>top_3_buyers_volume_share_5m</li>
              <li>new_wallet_pct_5m</li>
            </ul>
          </div>
          <div>
            <h4 className="text-gray-400 mb-2">1-Hour Window</h4>
            <ul className="space-y-1 text-gray-500 font-mono text-xs">
              <li>buy_count_1h</li>
              <li>sell_count_1h</li>
              <li>unique_buyers_1h</li>
              <li>unique_sellers_1h</li>
              <li>buy_volume_sol_1h</li>
              <li>avg_buy_size_1h</li>
              <li>buy_sell_ratio_1h</li>
              <li>top_3_buyers_volume_share_1h</li>
              <li>new_wallet_pct_1h</li>
            </ul>
          </div>
          <div>
            <h4 className="text-gray-400 mb-2">Operators</h4>
            <ul className="space-y-1 text-gray-500 font-mono text-xs">
              <li>&gt;=  (greater or equal)</li>
              <li>&gt;   (greater than)</li>
              <li>&lt;=  (less or equal)</li>
              <li>&lt;   (less than)</li>
              <li>==  (equal)</li>
            </ul>
            <h4 className="text-gray-400 mt-4 mb-2">Example</h4>
            <code className="text-xs text-pw-blue">
              buy_count_5m &gt;= 20
            </code>
          </div>
        </div>
      </div>
    </div>
  )
}
