import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Box, CircularProgress, CssBaseline, PaletteMode, ThemeProvider } from '@mui/material'
import AppShell from './components/layout/AppShell'
import UnifiedAgentView from './components/UnifiedAgentView'
import { buildAppTheme } from './theme/appTheme'

const LogsView = lazy(() => import('./components/logs/LogsView'))

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
          <Suspense
            fallback={
              <Box sx={{ display: 'grid', placeItems: 'center', minHeight: 280 }}>
                <CircularProgress size={28} />
              </Box>
            }
          >
            <Routes>
              <Route path="/" element={<UnifiedAgentView />} />
              <Route path="/chat" element={<UnifiedAgentView />} />
              <Route path="/logs" element={<LogsView />} />
            </Routes>
          </Suspense>
        </AppShell>
        <Toaster richColors position="bottom-right" />
      </Router>
    </ThemeProvider>
  )
}
