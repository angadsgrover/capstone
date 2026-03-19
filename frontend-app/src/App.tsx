import { lazy, Suspense } from 'react'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import AppShell from './components/layout/AppShell'
import ChatView from './components/chat/ChatView'

const WorkflowView = lazy(() => import('./components/workflow/WorkflowView'))
const LogsView = lazy(() => import('./components/logs/LogsView'))
const VisualizationsView = lazy(() => import('./components/visualizations/VisualizationsView'))

export default function App() {
  return (
    <Router>
      <AppShell>
        <Suspense fallback={<div className="text-sm text-muted-foreground">Loading view…</div>}>
          <Routes>
            <Route path="/" element={<ChatView />} />
            <Route path="/chat" element={<ChatView />} />
            <Route path="/workflow" element={<WorkflowView />} />
            <Route path="/logs" element={<LogsView />} />
            <Route path="/visuals" element={<VisualizationsView />} />
          </Routes>
        </Suspense>
      </AppShell>
      <Toaster richColors position="bottom-right" />
    </Router>
  )
}
