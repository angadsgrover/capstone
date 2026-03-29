import { lazy, Suspense } from 'react'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import AppShell from './components/layout/AppShell'
import UnifiedAgentView from './components/UnifiedAgentView'

const LogsView = lazy(() => import('./components/logs/LogsView'))

export default function App() {
  return (
    <Router>
      <AppShell>
        <Suspense fallback={<div className="text-sm text-muted-foreground">Loading view…</div>}>
          <Routes>
            <Route path="/" element={<UnifiedAgentView />} />
            <Route path="/chat" element={<UnifiedAgentView />} />
            <Route path="/logs" element={<LogsView />} />
          </Routes>
        </Suspense>
      </AppShell>
      <Toaster richColors position="bottom-right" />
    </Router>
  )
}
