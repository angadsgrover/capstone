import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  Moon, Sun, Bot, MessageSquare, GitBranch,
  Terminal, BarChart3, Settings, ChevronLeft, ChevronRight,
  Sparkles
} from 'lucide-react'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { label: 'Chat',          path: '/chat',     icon: MessageSquare, short: '1' },
  { label: 'Workflow',      path: '/workflow', icon: GitBranch,     short: '2' },
  { label: 'Logs',          path: '/logs',     icon: Terminal,      short: '3' },
  { label: 'Visualizations', path: '/visuals', icon: BarChart3,     short: '4' },
]

interface AppShellProps {
  children: React.ReactNode
}

export default function AppShell({ children }: AppShellProps) {
  const navigate  = useNavigate()
  const location  = useLocation()
  const [isDark, setIsDark] = useState(true)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  // Init dark mode from localStorage (default: dark)
  useEffect(() => {
    const stored = localStorage.getItem('darkMode')
    setIsDark(stored !== null ? stored === 'true' : true)
    const sidebarStored = localStorage.getItem('sidebarCollapsed')
    setSidebarCollapsed(sidebarStored === 'true')
  }, [])

  // Apply dark class and persist
  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark)
    localStorage.setItem('darkMode', String(isDark))
  }, [isDark])

  // Persist sidebar state
  useEffect(() => {
    localStorage.setItem('sidebarCollapsed', String(sidebarCollapsed))
  }, [sidebarCollapsed])

  // Keyboard shortcuts: ⌘1/2/3/4 → switch tabs
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
    <div className="flex h-dvh bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-foreground antialiased overflow-hidden">

      {/* ── Sidebar ──────────────────────────────────────────────── */}
      <aside
        className={cn(
          "relative flex flex-col h-full border-r border-white/[0.06] bg-slate-900/50 backdrop-blur-xl transition-all duration-300 ease-out",
          sidebarCollapsed ? "w-[72px]" : "w-[260px]"
        )}
      >
        {/* Logo */}
        <div className={cn(
          "flex items-center gap-3 px-4 h-16 border-b border-white/[0.06]",
          sidebarCollapsed && "justify-center px-0"
        )}>
          <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 via-violet-500 to-purple-600 shadow-lg shadow-indigo-500/25 flex-shrink-0">
            <Bot className="h-5 w-5 text-white" />
            <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-white/20 to-transparent" />
            <Sparkles className="absolute -top-1 -right-1 h-3 w-3 text-amber-400 animate-pulse" />
          </div>
          {!sidebarCollapsed && (
            <div className="overflow-hidden">
              <p className="text-sm font-bold tracking-tight text-white">Aviation AI</p>
              <p className="text-[10px] text-white/40 truncate">Weather Intelligence</p>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item) => {
            const active = currentPath === item.path
            const Icon = item.icon
            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                title={sidebarCollapsed ? `${item.label} (⌘${item.short})` : undefined}
                className={cn(
                  "group relative w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/50",
                  active
                    ? "bg-gradient-to-r from-indigo-500/15 to-purple-500/10 text-white shadow-sm"
                    : "text-white/50 hover:text-white/90 hover:bg-white/[0.05]",
                  sidebarCollapsed && "justify-center px-0"
                )}
              >
                {/* Active indicator */}
                {active && (
                  <span className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 rounded-r-full bg-gradient-to-b from-indigo-400 to-purple-500" />
                )}
                <Icon className={cn(
                  "h-[18px] w-[18px] flex-shrink-0 transition-transform duration-200",
                  active ? "text-indigo-400" : "text-white/40 group-hover:text-white/70",
                  !sidebarCollapsed && "group-hover:scale-110"
                )} />
                {!sidebarCollapsed && (
                  <>
                    <span className="flex-1 text-left">{item.label}</span>
                    <kbd className="hidden sm:inline-flex h-5 items-center rounded-md bg-white/[0.06] px-1.5 text-[10px] font-mono text-white/30">
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
          "border-t border-white/[0.06] p-3 space-y-1",
          sidebarCollapsed && "px-2"
        )}>
          {/* Theme toggle */}
          <button
            onClick={toggleDark}
            className={cn(
              "w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-white/50 hover:text-white/90 hover:bg-white/[0.05] transition-all duration-200",
              sidebarCollapsed && "justify-center px-0"
            )}
          >
            {isDark ? (
              <Sun className="h-[18px] w-[18px] text-amber-400 flex-shrink-0" />
            ) : (
              <Moon className="h-[18px] w-[18px] text-indigo-400 flex-shrink-0" />
            )}
            {!sidebarCollapsed && <span>{isDark ? 'Light mode' : 'Dark mode'}</span>}
          </button>

          {/* Settings placeholder */}
          <button
            className={cn(
              "w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-white/50 hover:text-white/90 hover:bg-white/[0.05] transition-all duration-200",
              sidebarCollapsed && "justify-center px-0"
            )}
          >
            <Settings className="h-[18px] w-[18px] flex-shrink-0" />
            {!sidebarCollapsed && <span>Settings</span>}
          </button>
        </div>

        {/* Collapse toggle */}
        <button
          onClick={toggleSidebar}
          className="absolute -right-3 top-20 flex h-6 w-6 items-center justify-center rounded-full bg-slate-800 border border-white/10 text-white/50 hover:text-white hover:bg-slate-700 transition-all duration-200 shadow-lg"
        >
          {sidebarCollapsed ? (
            <ChevronRight className="h-3.5 w-3.5" />
          ) : (
            <ChevronLeft className="h-3.5 w-3.5" />
          )}
        </button>
      </aside>

      {/* ── Main Content ─────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top bar */}
        <header className="flex items-center justify-between h-14 px-6 border-b border-white/[0.06] bg-slate-900/30 backdrop-blur-sm flex-shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-white/80">
              {NAV_ITEMS.find(i => i.path === currentPath)?.label || 'Chat'}
            </span>
            <span className="text-xs text-white/30">|</span>
            <span className="inline-flex items-center gap-1.5 text-xs text-white/40">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Online
            </span>
          </div>
          <div className="flex items-center gap-3">
            <kbd className="hidden lg:inline-flex h-6 items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 text-[10px] font-mono text-white/40">
              ⌘K clear
            </kbd>
          </div>
        </header>

        {/* Page content */}
        <div className="flex-1 overflow-y-auto">
          <div className="h-full max-w-6xl mx-auto px-6 py-6">
            {children}
          </div>
        </div>
      </main>
    </div>
  )
}
