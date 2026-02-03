import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import LiveStream from './pages/LiveStream'
import Calendar from './pages/Calendar'
import Backtest from './pages/Backtest'
import Triggers from './pages/Triggers'
import Settings from './pages/Settings'

function NavItem({ to, children }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `px-4 py-2 rounded-lg transition-colors ${
          isActive
            ? 'bg-pw-blue text-white'
            : 'text-gray-400 hover:text-white hover:bg-pw-card'
        }`
      }
    >
      {children}
    </NavLink>
  )
}

export default function App() {
  return (
    <div className="min-h-screen bg-pw-dark">
      {/* Header */}
      <header className="bg-pw-card border-b border-pw-border">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-2xl">🔍</span>
            <h1 className="text-xl font-bold text-white">Pocketwatcher</h1>
          </div>
          <nav className="flex gap-2">
            <NavItem to="/">Dashboard</NavItem>
            <NavItem to="/live">Live</NavItem>
            <NavItem to="/calendar">Calendar</NavItem>
            <NavItem to="/backtest">Backtest</NavItem>
            <NavItem to="/triggers">Triggers</NavItem>
            <NavItem to="/settings">Settings</NavItem>
          </nav>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/live" element={<LiveStream />} />
          <Route path="/calendar" element={<Calendar />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/triggers" element={<Triggers />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}
