import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Moon, Sun, Bot } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const TABS = [
  { label: 'Chat',     path: '/chat',     short: '1' },
  { label: 'Workflow', path: '/workflow', short: '2' },
  { label: 'Logs',     path: '/logs',     short: '3' },
  { label: 'Visuals',  path: '/visuals',  short: '4' },
]

interface AppShellProps {
  children: React.ReactNode
}

export default function AppShell({ children }: AppShellProps) {
  const navigate  = useNavigate()
  const location  = useLocation()
  const [isDark, setIsDark] = useState(false)

  // Init dark mode from localStorage or system preference
  useEffect(() => {
    const stored = localStorage.getItem('darkMode')
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    setIsDark(stored !== null ? stored === 'true' : prefersDark)
  }, [])

  // Apply dark class and persist
  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark)
    localStorage.setItem('darkMode', String(isDark))
  }, [isDark])

  // Keyboard shortcuts: ⌘1/2/3/4 → switch tabs
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return
      const tab = TABS.find((t) => t.short === e.key)
      if (tab) { e.preventDefault(); navigate(tab.path) }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [navigate])

  const currentPath = location.pathname === '/' ? '/chat' : location.pathname
  const toggleDark  = useCallback(() => setIsDark((d) => !d), [])

  return (
    <div className="flex h-dvh flex-col bg-transparent text-foreground antialiased">

      {/* ── Header ──────────────────────────────────────────────── */}
      <header className="sticky top-0 z-40 border-b border-white/45 bg-white/45 backdrop-blur-xl supports-[backdrop-filter]:bg-white/35 dark:border-slate-700/70 dark:bg-slate-900/45">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="flex h-16 items-center gap-4">

            {/* Logo */}
            <div className="flex items-center gap-2 mr-4 flex-shrink-0">
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-sky-500 shadow-sm">
                <Bot className="h-4 w-4 text-primary-foreground" />
              </div>
              <div className="hidden sm:block">
                <p className="text-sm font-semibold tracking-tight">Aviation AI</p>
                <p className="text-[11px] text-muted-foreground">Pilot-ready weather and route intelligence</p>
              </div>
            </div>

            {/* Tab navigation */}
            <nav className="flex items-center gap-1 flex-1">
              {TABS.map((tab) => {
                const active = currentPath === tab.path
                return (
                  <button
                    key={tab.path}
                    onClick={() => navigate(tab.path)}
                    title={`${tab.label} (⌘${tab.short})`}
                    className={cn(
                      'relative h-9 px-3 rounded-lg text-sm font-semibold transition-all select-none',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      active
                        ? 'bg-white/80 text-foreground shadow-sm dark:bg-slate-800/90'
                        : 'text-muted-foreground hover:text-foreground hover:bg-white/55 dark:hover:bg-slate-800/70',
                    )}
                  >
                    {tab.label}
                    <span className="ml-1.5 hidden md:inline text-[10px] font-mono opacity-40">⌘{tab.short}</span>
                    {active && (
                      <span className="absolute bottom-0 left-3 right-3 h-0.5 rounded-full bg-primary" />
                    )}
                  </button>
                )
              })}
            </nav>

            {/* Actions */}
            <div className="flex items-center gap-2 flex-shrink-0">
              <kbd className="hidden lg:inline-flex h-5 items-center gap-1 rounded border bg-muted px-1.5 text-[10px] font-mono text-muted-foreground">
                ⌘K clear
              </kbd>
                <Button variant="ghost" size="icon" className="bg-white/65 hover:bg-white dark:bg-slate-800/75 dark:hover:bg-slate-700" onClick={toggleDark} aria-label="Toggle theme">
                {isDark
                  ? <Sun className="h-4 w-4 text-yellow-400" />
                  : <Moon className="h-4 w-4" />
                }
              </Button>
            </div>

          </div>
        </div>
      </header>

      {/* ── Content ─────────────────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
          {children}
        </div>
      </main>

    </div>
  )
}
