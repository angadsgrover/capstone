import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import MaterialIcon from '@/components/ui/MaterialIcon'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { label: 'Agent',          path: '/chat',     icon: 'chat_bubble',     short: '1' },
  { label: 'Logs',           path: '/logs',     icon: 'terminal',        short: '2' },
  { label: 'Visuals',        path: '/visuals',  icon: 'monitoring',      short: '3' },
]

interface AppShellProps {
  children: React.ReactNode
}

export default function AppShell({ children }: AppShellProps) {
  const navigate  = useNavigate()
  const location  = useLocation()
  const [isDark, setIsDark] = useState(true)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  useEffect(() => {
    const stored = localStorage.getItem('darkMode')
    setIsDark(stored !== null ? stored === 'true' : true)
    const sidebarStored = localStorage.getItem('sidebarCollapsed')
    setSidebarCollapsed(sidebarStored === 'true')
  }, [])

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark)
    localStorage.setItem('darkMode', String(isDark))
  }, [isDark])

  useEffect(() => {
    localStorage.setItem('sidebarCollapsed', String(sidebarCollapsed))
  }, [sidebarCollapsed])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return
      const item = NAV_ITEMS.find((t) => t.short === e.key)
      if (item) { e.preventDefault(); navigate(item.path) }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [navigate])

  const currentPath = location.pathname === '/' ? '/chat' : location.pathname
  const toggleDark = useCallback(() => setIsDark((d) => !d), [])
  const toggleSidebar = useCallback(() => setSidebarCollapsed((c) => !c), [])

  return (
    <div className={cn(
      "flex h-dvh antialiased overflow-hidden transition-colors duration-300",
      "bg-surface text-on-surface"
    )}>

      {/* ── Sidebar ────────────────────────────────────────────────── */}
      <aside
        className={cn(
          "relative flex flex-col h-full transition-all duration-300 ease-in-out",
          "bg-surface-container-low shadow-[4px_0_24px_rgba(0,0,0,0.3)]",
          sidebarCollapsed ? "w-[64px]" : "w-[260px]",
          "group"
        )}
      >
        {/* Logo */}
        <div className={cn(
          "flex items-center gap-3 px-4 h-16",
          sidebarCollapsed && "justify-center px-0"
        )}>
          <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-primary-container to-secondary shadow-lg flex-shrink-0">
            <MaterialIcon icon="flight_takeoff" className="text-on-primary-container text-xl" filled />
            <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-white/20 to-transparent pointer-events-none" />
          </div>
          {!sidebarCollapsed && (
            <div className="overflow-hidden">
              <p className="text-sm font-bold tracking-tight text-primary">PolyU Aviation</p>
              <p className="text-[10px] text-on-surface-variant uppercase tracking-wider">Weather Intelligence</p>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2 py-4 space-y-2 overflow-y-auto">
          {NAV_ITEMS.map((item) => {
            const active = currentPath === item.path
            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                title={sidebarCollapsed ? `${item.label} (⌘${item.short})` : undefined}
                className={cn(
                  "group/item relative w-full flex items-center gap-4 px-3 h-12 rounded-lg text-sm font-semibold transition-all duration-200",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary/50",
                  active
                    ? "bg-surface-container-high text-secondary border-l-4 border-secondary scale-[1.02]"
                    : "text-on-surface-variant hover:bg-surface-container-high/70 hover:text-secondary hover:scale-[1.01] border-l-4 border-transparent",
                  sidebarCollapsed && "justify-center px-0"
                )}
              >
                <MaterialIcon
                  icon={item.icon}
                  className={cn(
                    "flex-shrink-0 transition-colors",
                    active ? "text-secondary" : "text-on-surface-variant group-hover/item:text-secondary"
                  )}
                />
                {!sidebarCollapsed && (
                  <>
                    <span className="flex-1 text-left">
                      {item.label}
                    </span>
                    <kbd className={cn(
                      "h-5 px-1.5 rounded bg-surface-container-highest/50 border border-outline-variant/20",
                      "text-[10px] font-mono text-on-surface-variant",
                      "flex items-center justify-center"
                    )}>
                      ⌘{item.short}
                    </kbd>
                  </>
                )}
              </button>
            )
          })}
        </nav>

        {/* Bottom actions */}
        <div className={cn(
          "pt-6 mt-auto border-t border-outline-variant/10 space-y-2 px-2",
          sidebarCollapsed && "px-2"
        )}>
          <button
            onClick={toggleDark}
            className={cn(
              "w-full flex items-center gap-4 px-3 h-12 rounded-lg text-sm font-medium transition-all duration-200",
              "text-on-surface-variant hover:bg-surface-container-high hover:text-secondary hover:scale-[1.02]",
              sidebarCollapsed && "justify-center px-0"
            )}
          >
            <MaterialIcon
              icon={isDark ? "dark_mode" : "light_mode"}
              className="flex-shrink-0"
            />
            {!sidebarCollapsed && (
              <span>
                {isDark ? 'Dark mode' : 'Light mode'}
              </span>
            )}
          </button>
        </div>

        {/* Collapse toggle button */}
        <button
          onClick={toggleSidebar}
          className={cn(
            "absolute -right-3 top-20 flex h-6 w-6 items-center justify-center rounded-full shadow-lg transition-all duration-200 z-10",
            "bg-surface-container-high border border-outline-variant/20",
            "text-on-surface-variant hover:text-secondary hover:bg-surface-container-highest"
          )}
        >
          <MaterialIcon
            icon={sidebarCollapsed ? "chevron_right" : "chevron_left"}
            className="text-sm"
          />
        </button>
      </aside>

      {/* ── Main Content ───────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top bar */}
        <header className={cn(
          "flex items-center justify-between h-16 px-8 flex-shrink-0",
          "bg-background/80 backdrop-blur-xl",
          "bg-gradient-to-b from-surface-container-low to-transparent"
        )}>
          <div className="flex items-center gap-6">
            <span className="text-base font-bold tracking-tight text-primary">
              PolyU Aviation Weather Intelligence
            </span>
            <div className="h-4 w-[1px] bg-outline-variant/30"></div>
            <div className="flex items-center gap-2 text-secondary text-xs font-medium uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full bg-secondary animate-pulse shadow-glow-secondary"></span>
              Live
            </div>
          </div>
        </header>

        {/* Page content */}
        <div className="flex-1 overflow-y-auto">
          {children}
        </div>
      </main>
    </div>
  )
}
