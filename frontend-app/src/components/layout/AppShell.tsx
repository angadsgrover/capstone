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
  const [isDark, setIsDark] = useState(true)

  // Init dark mode from localStorage (default: dark)
  useEffect(() => {
    const stored = localStorage.getItem('darkMode')
    // Default to dark mode if no preference stored
    setIsDark(stored !== null ? stored === 'true' : true)
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
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-[hsl(228_22%_10%)]/80 backdrop-blur-2xl supports-[backdrop-filter]:bg-[hsl(228_22%_10%)]/70 dark:border-white/[0.06]">
        <div className="mx-auto max-w-7xl px-4 sm:px-6">
          <div className="flex h-16 items-center gap-4">

            {/* Logo */}
            <div className="flex items-center gap-3 mr-6 flex-shrink-0">
              <div className="relative flex h-10 w-10 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 shadow-lg shadow-indigo-500/25">
                <Bot className="h-5 w-5 text-white" />
                <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-white/20 to-transparent" />
              </div>
              <div className="hidden sm:block">
                <p className="text-sm font-bold tracking-tight bg-gradient-to-r from-white to-white/70 bg-clip-text text-transparent">Aviation AI</p>
                <p className="text-[11px] text-muted-foreground/80">Intelligent weather & route analysis</p>
              </div>
            </div>

            {/* Tab navigation */}
            <nav className="flex items-center gap-1.5 flex-1">
              {TABS.map((tab) => {
                const active = currentPath === tab.path
                return (
                  <button
                    key={tab.path}
                    onClick={() => navigate(tab.path)}
                    title={`${tab.label} (⌘${tab.short})`}
                    className={cn(
                      'relative h-9 px-4 rounded-xl text-sm font-medium transition-all duration-200 select-none',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
                      active
                        ? 'bg-white/10 text-white shadow-sm backdrop-blur-sm'
                        : 'text-white/50 hover:text-white/80 hover:bg-white/[0.05]',
                    )}
                  >
                    {tab.label}
                    <span className="ml-1.5 hidden md:inline text-[10px] font-mono opacity-40">⌘{tab.short}</span>
                    {active && (
                      <span className="absolute bottom-0 left-4 right-4 h-0.5 rounded-full bg-gradient-to-r from-indigo-400 to-purple-400" />
                    )}
                  </button>
                )
              })}
            </nav>

            {/* Actions */}
            <div className="flex items-center gap-3 flex-shrink-0">
              <kbd className="hidden lg:inline-flex h-6 items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 text-[10px] font-mono text-white/40">
                ⌘K clear
              </kbd>
              <Button
                variant="ghost"
                size="icon"
                className="rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 transition-all duration-200"
                onClick={toggleDark}
                aria-label="Toggle theme"
              >
                {isDark
                  ? <Sun className="h-4 w-4 text-amber-400" />
                  : <Moon className="h-4 w-4 text-indigo-300" />
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
