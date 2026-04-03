import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { BrowserRouter as Router, useLocation } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Box, CircularProgress, CssBaseline, PaletteMode, ThemeProvider } from '@mui/material'
import AppShell from './components/layout/AppShell'
import UnifiedAgentView from './components/UnifiedAgentView'
import { buildAppTheme } from './theme/appTheme'

const LogsView = lazy(() => import('./components/logs/LogsView'))

function PersistentViews() {
  const location = useLocation()
  const normalizedPath = location.pathname === '/' ? '/chat' : location.pathname
  const showLogs = normalizedPath === '/logs'

  return (
    <Suspense
      fallback={
        <Box sx={{ display: 'grid', placeItems: 'center', minHeight: 280 }}>
          <CircularProgress size={28} />
        </Box>
      }
    >
      <Box sx={{ height: '100%', minHeight: 0 }}>
        <Box sx={{ display: showLogs ? 'none' : 'block', height: '100%', minHeight: 0 }}>
          <UnifiedAgentView />
        </Box>
        <Box sx={{ display: showLogs ? 'block' : 'none', height: '100%', minHeight: 0 }}>
          <LogsView />
        </Box>
      </Box>
    </Suspense>
  )
}

export default function App() {
  const [mode, setMode] = useState<PaletteMode>('dark')

  useEffect(() => {
    const stored = localStorage.getItem('darkMode')
    setMode(stored !== null ? (stored === 'true' ? 'dark' : 'light') : 'dark')
  }, [])

  useEffect(() => {
    localStorage.setItem('darkMode', String(mode === 'dark'))
  }, [mode])

  const theme = useMemo(() => buildAppTheme(mode), [mode])

  const toggleColorMode = () => {
    setMode((prev) => (prev === 'dark' ? 'light' : 'dark'))
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Router>
        <AppShell mode={mode} onToggleMode={toggleColorMode}>
          <PersistentViews />
        </AppShell>
        <Toaster richColors position="bottom-right" />
      </Router>
    </ThemeProvider>
  )
}
