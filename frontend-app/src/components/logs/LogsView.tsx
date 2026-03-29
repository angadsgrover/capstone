import { useState, useEffect, useRef, useCallback } from 'react'
import { FixedSizeList, type ListChildComponentProps } from 'react-window'
import { streamAgent } from '@/shared/services/streamService'
import MaterialIcon from '@/components/ui/MaterialIcon'
import { cn } from '@/lib/utils'

const API_BASE = import.meta.env.VITE_AGENT_API_URL ?? 'http://localhost:8000'
const CHAT_SESSION_KEY = 'chatSessionId'

// Get the same session ID used by the chat
function getChatSessionId(): string {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') {
    return 'default'
  }
  return localStorage.getItem(CHAT_SESSION_KEY) || 'default'
}

interface BackendStatus {
  langsmith: boolean
  langsmithProject: string
  langsmithEndpoint: string
  langsmithMessage: string
  langsmithUiUrl: string
  langsmithDashboardUrl: string
  tracingMiddlewareEnabled: boolean
  eventBackend: string
  eventAvailable: boolean
  trackedSessions: number
}

async function fetchBackendStatus(): Promise<BackendStatus | null> {
  try {
    const res = await fetch(`${API_BASE}/api/status`)
    if (!res.ok) return null
    const data = await res.json()
    return {
      langsmith: data.langsmith?.enabled ?? false,
      langsmithProject: data.langsmith?.project ?? 'default',
      langsmithEndpoint: data.langsmith?.endpoint ?? 'https://api.smith.langchain.com',
      langsmithMessage: data.langsmith?.message ?? 'Status unavailable',
      langsmithUiUrl: data.langsmith?.ui_url ?? 'https://smith.langchain.com',
      langsmithDashboardUrl: data.langsmith?.dashboard_url ?? 'https://smith.langchain.com/monitor',
      tracingMiddlewareEnabled: data.langsmith?.tracing_middleware_enabled ?? false,
      eventBackend: data.event_tracking?.backend ?? 'memory',
      eventAvailable: data.event_tracking?.available ?? false,
      trackedSessions: data.event_tracking?.tracked_sessions ?? 0,
    }
  } catch {
    return null
  }
}

interface LogEvent {
  id: string
  timestamp: Date
  nodeId: string
  event_type: string
  status: string
  label: string
  details: string
  duration_ms?: number
  route?: string
  step?: number
  tool_input?: Record<string, unknown>
  parent_node?: string
  run_id?: string
  parent_run_id?: string
  trace_id?: string
  root_run_id?: string
  project?: string
  ui_url?: string
  dashboard_url?: string
  distributed_headers?: Record<string, unknown>
  raw: Record<string, unknown>
}

const TYPE_CONFIG: Record<string, { icon: string; colorClass: string; bgClass: string; label: string }> = {
  node: { icon: 'circle', colorClass: 'text-secondary', bgClass: 'bg-secondary/10 border-secondary/30', label: 'Node' },
  trace_context: { icon: 'hub', colorClass: 'text-primary', bgClass: 'bg-primary/10 border-primary/30', label: 'Trace' },
  routing_decision: { icon: 'alt_route', colorClass: 'text-primary', bgClass: 'bg-primary/10 border-primary/30', label: 'Route' },
  tool: { icon: 'build', colorClass: 'text-tertiary', bgClass: 'bg-tertiary/10 border-tertiary/30', label: 'Tool' },
  reasoning: { icon: 'psychology', colorClass: 'text-secondary', bgClass: 'bg-secondary/10 border-secondary/30',  label: 'Think' },
  internal: { icon: 'settings', colorClass: 'text-on-surface-variant/50', bgClass: 'bg-surface-container border-outline-variant/30', label: 'Internal' },
  error: { icon: 'error', colorClass: 'text-error', bgClass: 'bg-error/10 border-error/30', label: 'Error' },
}

const STATUS_COLORS: Record<string, string> = {
  started: 'bg-secondary/10 text-secondary border-secondary/30',
  running: 'bg-secondary/10 text-secondary border-secondary/30',
  completed: 'bg-[hsl(var(--status-vfr)/0.12)] text-[hsl(var(--status-vfr))] border-[hsl(var(--status-vfr)/0.3)]',
  failed: 'bg-error/10 text-error border-error/30',
  error: 'bg-error/10 text-error border-error/30',
}

type FilterType = 'all' | 'trace_context' | 'node' | 'tool' | 'routing_decision' | 'reasoning' | 'internal'

function fmtTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
    `.${String(d.getMilliseconds()).padStart(3, '0')}`
}

async function copyText(value: string): Promise<void> {
  if (!value) return
  try {
    await navigator.clipboard.writeText(value)
  } catch {
    // ignore clipboard errors
  }
}

function buildLangSmithSearchUrl(baseUrl: string | undefined, query: string): string | undefined {
  if (!baseUrl || !query) return undefined
  try {
    const url = new URL('/monitor', baseUrl)
    url.searchParams.set('q', query)
    return url.toString()
  } catch {
    return undefined
  }
}

function eventSignature(data: Record<string, unknown>): string {
  const normalized = {
    nodeId: data.nodeId ?? '',
    event_type: data.event_type ?? '',
    status: data.status ?? '',
    label: data.label ?? '',
    details: data.details ?? '',
    duration_ms: data.duration_ms ?? '',
    route: data.route ?? '',
    step: data.step ?? '',
    parent_node: data.parent_node ?? '',
    run_id: data.run_id ?? '',
    parent_run_id: data.parent_run_id ?? '',
    trace_id: data.trace_id ?? '',
    root_run_id: data.root_run_id ?? '',
    timestamp: data.timestamp ?? '',
    tool_input: data.tool_input ?? '',
  }
  return JSON.stringify(normalized)
}

function TypeBadge({ type }: { type: string }) {
  const config = TYPE_CONFIG[type] ?? TYPE_CONFIG.node
  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-semibold uppercase tracking-wider border",
      config.bgClass, config.colorClass
    )}>
      <MaterialIcon icon={config.icon} className="text-sm" filled />
      {config.label}
    </span>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colorClass = STATUS_COLORS[status] ?? 'bg-surface-container text-on-surface-variant border-outline-variant/30'
  return (
    <span className={cn(
      "inline-flex items-center px-2.5 py-1 rounded-lg text-[10px] font-semibold uppercase tracking-wider border",
      colorClass
    )}>
      {status}
    </span>
  )
}

export default function LogsView() {
  const [events, setEvents] = useState<LogEvent[]>([])
  const [isWatching, setIsWatching] = useState(false)
  const [filter, setFilter] = useState<FilterType>('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [showEmbeddedDashboard, setShowEmbeddedDashboard] = useState(false)
  const [backendStatus, setBackendStatus] = useState<BackendStatus | null>(null)
  const cancelRef = useRef<(() => void) | null>(null)
  const connectStreamRef = useRef<(sessionId: string) => void>(() => {})
  const reconnectTimerRef = useRef<number | null>(null)
  const shouldWatchRef = useRef(false)
  const seenEventSignaturesRef = useRef<Set<string>>(new Set())
  const tableEndRef = useRef<HTMLDivElement>(null)
  const startedRef = useRef(false)

  // Fetch backend status on mount
  useEffect(() => {
    fetchBackendStatus().then(setBackendStatus)
  }, [])

  useEffect(() => {
    tableEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  useEffect(() => {
    return () => {
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      cancelRef.current?.()
    }
  }, [])

  const connectStream = useCallback((sessionId: string) => {
    if (cancelRef.current) {
      cancelRef.current()
      cancelRef.current = null
    }

    setIsWatching(true)
    cancelRef.current = streamAgent(`${API_BASE}/api/agent/events?session_id=${encodeURIComponent(sessionId)}`, {
      onChunk: (rawData) => {
        try {
          const data = JSON.parse(rawData)
          if (data.__done__) return

          const signature = eventSignature(data as Record<string, unknown>)
          if (seenEventSignaturesRef.current.has(signature)) {
            return
          }
          seenEventSignaturesRef.current.add(signature)
          if (seenEventSignaturesRef.current.size > 5000) {
            seenEventSignaturesRef.current.clear()
          }

          const event: LogEvent = {
            id: `${Date.now()}-${Math.random()}`,
            timestamp: new Date(),
            nodeId: data.nodeId ?? '—',
            event_type: data.event_type ?? 'node',
            status: data.status ?? '—',
            label: data.label ?? data.nodeId ?? '—',
            details: typeof data.details === 'string' ? data.details : JSON.stringify(data.details ?? {}),
            duration_ms: typeof data.duration_ms === 'number' ? data.duration_ms : undefined,
            route: data.route,
            step: typeof data.step === 'number' ? data.step : undefined,
            tool_input: data.tool_input,
            parent_node: data.parent_node,
            run_id: typeof data.run_id === 'string' ? data.run_id : undefined,
            parent_run_id: typeof data.parent_run_id === 'string' ? data.parent_run_id : undefined,
            trace_id: typeof data.trace_id === 'string' ? data.trace_id : undefined,
            root_run_id: typeof data.root_run_id === 'string' ? data.root_run_id : undefined,
            project: typeof data.project === 'string' ? data.project : undefined,
            ui_url: typeof data.ui_url === 'string' ? data.ui_url : undefined,
            dashboard_url: typeof data.dashboard_url === 'string' ? data.dashboard_url : undefined,
            distributed_headers: data.distributed_headers,
            raw: data,
          }
          setEvents((prev) => [...prev, event])
        } catch {
          // ignore non-JSON keepalive
        }
      },
      onError: () => {
        cancelRef.current = null
        setIsWatching(false)
        if (!shouldWatchRef.current) return
        if (reconnectTimerRef.current !== null) {
          window.clearTimeout(reconnectTimerRef.current)
        }
        reconnectTimerRef.current = window.setTimeout(() => {
          reconnectTimerRef.current = null
          if (shouldWatchRef.current) {
            connectStreamRef.current(getChatSessionId())
          }
        }, 1200)
      },
      onComplete: () => {
        cancelRef.current = null
        setIsWatching(false)
        if (!shouldWatchRef.current) return
        if (reconnectTimerRef.current !== null) {
          window.clearTimeout(reconnectTimerRef.current)
        }
        reconnectTimerRef.current = window.setTimeout(() => {
          reconnectTimerRef.current = null
          if (shouldWatchRef.current) {
            connectStreamRef.current(getChatSessionId())
          }
        }, 350)
      },
    })
  }, [])

  connectStreamRef.current = connectStream

  const startWatching = useCallback(() => {
    shouldWatchRef.current = true
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    if (cancelRef.current || isWatching) return
    connectStream(getChatSessionId())
  }, [connectStream, isWatching])

  // Auto-start watching on mount
  useEffect(() => {
    if (!startedRef.current) {
      startedRef.current = true
      // Small delay to ensure component is fully mounted
      const timer = setTimeout(() => {
        startWatching()
      }, 100)
      return () => clearTimeout(timer)
    }
  }, [startWatching])

  const stopWatching = useCallback(() => {
    shouldWatchRef.current = false
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    cancelRef.current?.()
    cancelRef.current = null
    setIsWatching(false)
  }, [])

  const clearLogs = useCallback(() => {
    stopWatching()
    setEvents([])
    seenEventSignaturesRef.current.clear()
    setExpanded(null)
    setShowEmbeddedDashboard(false)
  }, [stopWatching])

  const exportJson = useCallback(() => {
    const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `agent-trace-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`
    a.click()
    URL.revokeObjectURL(url)
  }, [events])

  const filtered = filter === 'all' ? events : events.filter((e) => e.event_type === filter)

  const counts = events.reduce<Record<string, number>>((acc, e) => {
    acc[e.event_type] = (acc[e.event_type] ?? 0) + 1
    return acc
  }, {})

  const FILTERS: { key: FilterType; label: string; count: number }[] = [
    { key: 'all', label: 'All', count: events.length },
    { key: 'trace_context', label: 'Trace', count: counts.trace_context ?? 0 },
    { key: 'node', label: 'Nodes', count: counts.node ?? 0 },
    { key: 'routing_decision', label: 'Route', count: counts.routing_decision ?? 0 },
    { key: 'tool', label: 'Tools', count: counts.tool ?? 0 },
    { key: 'reasoning', label: 'Think', count: counts.reasoning ?? 0 },
    { key: 'internal', label: 'Internal', count: counts.internal ?? 0 },
  ]

  const latestTraceContext = [...events].reverse().find(
    (e) => e.event_type === 'trace_context' || !!e.trace_id || !!e.root_run_id
  )
  const langsmithUiUrl = latestTraceContext?.ui_url || backendStatus?.langsmithUiUrl
  const langsmithDashboardUrl = latestTraceContext?.dashboard_url || backendStatus?.langsmithDashboardUrl
  const traceId = latestTraceContext?.trace_id
  const rootRunId = latestTraceContext?.root_run_id
  const langsmithProject = latestTraceContext?.project || backendStatus?.langsmithProject || ''
  const traceSearchQuery = traceId ? `trace_id:${traceId}${langsmithProject ? ` project:${langsmithProject}` : ''}` : ''
  const runSearchQuery = rootRunId ? `run_id:${rootRunId}${langsmithProject ? ` project:${langsmithProject}` : ''}` : ''
  const traceSearchUrl = buildLangSmithSearchUrl(langsmithUiUrl, traceSearchQuery)
  const runSearchUrl = buildLangSmithSearchUrl(langsmithUiUrl, runSearchQuery)

  const Row = ({ index, style, data }: ListChildComponentProps<{ rows: LogEvent[] }>) => {
    const ev = data.rows[index]
    return (
      <div
        style={style}
        className={cn(
          "border-b border-outline-variant/10 px-4 py-3 text-xs grid grid-cols-[48px_100px_80px_140px_80px_1fr_70px_32px] gap-3 items-center",
          "hover:bg-surface-container-high/50 transition-colors duration-200"
        )}
      >
        <div className="text-[10px] text-on-surface-variant/50 tabular-nums font-mono">{index + 1}</div>
        <div className="text-[10px] text-on-surface-variant tabular-nums font-mono">{fmtTime(ev.timestamp)}</div>
        <div><TypeBadge type={ev.event_type} /></div>
        <div className="font-mono font-medium text-on-surface truncate">{ev.label || ev.nodeId}</div>
        <div><StatusBadge status={ev.status} /></div>
        <div className="text-on-surface-variant truncate">{ev.details}</div>
        <div className="text-right tabular-nums font-mono text-on-surface-variant/70 flex items-center justify-end gap-1">
          <MaterialIcon icon="bolt" className="text-xs" />
          {ev.duration_ms !== undefined ? ev.duration_ms.toLocaleString() : '—'}
        </div>
        <button
          type="button"
          className={cn(
            "p-1 rounded-md hover:bg-surface-container-highest transition-colors duration-200",
            "active:scale-95"
          )}
          onClick={() => setExpanded(expanded === ev.id ? null : ev.id)}
        >
          <MaterialIcon
            icon={expanded === ev.id ? "expand_more" : "chevron_right"}
            className="text-base text-on-surface-variant"
          />
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6 p-6 h-full">
      {/* Header Card */}
      <div className={cn(
        "glass-panel rounded-2xl p-6 border border-outline-variant/20",
        "bg-surface-container-low/80 shadow-xl"
      )}>
        <div className="flex flex-wrap items-start gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-2">
              <MaterialIcon icon="analytics" className="text-2xl text-secondary" />
              <h2 className="text-lg font-bold text-primary">Event Trace</h2>
              {isWatching && (
                <span className={cn(
                  "inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold uppercase tracking-wider",
                  "bg-secondary/10 text-secondary border border-secondary/30"
                )}>
                  <span className="w-2 h-2 rounded-full bg-secondary animate-pulse shadow-glow-secondary" />
                  Live
                </span>
              )}
            </div>
            <p className="text-sm text-on-surface-variant flex items-center gap-2">
              <MaterialIcon icon="schedule" className="text-base" />
              {events.length} event{events.length !== 1 ? 's' : ''} captured
            </p>

            {/* Filter chips */}
            <div className="flex flex-wrap gap-2 mt-4">
              {FILTERS.map((f) => (
                <button
                  key={f.key}
                  onClick={() => setFilter(f.key)}
                  className={cn(
                    "px-4 py-2 rounded-xl text-xs font-semibold border transition-all duration-300",
                    filter === f.key
                      ? "user-gradient text-on-primary-container border-transparent shadow-lg shadow-primary/20 scale-105"
                      : "bg-surface-container-high text-on-surface-variant border-outline-variant/20 hover:border-secondary/30 hover:bg-surface-container-highest hover:scale-105 active:scale-95"
                  )}
                >
                  {f.label} ({f.count})
                </button>
              ))}
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex gap-2 flex-wrap">
            {isWatching ? (
              <button
                onClick={stopWatching}
                className={cn(
                  "flex items-center gap-2 px-4 py-2.5 rounded-xl font-semibold text-sm uppercase tracking-wider",
                  "bg-error/10 text-error border border-error/30",
                  "hover:bg-error/20 hover:scale-105 hover:shadow-lg hover:shadow-error/20",
                  "active:scale-95 transition-all duration-300"
                )}
              >
                <MaterialIcon icon="stop" className="text-base" filled />
                Stop
              </button>
            ) : (
              <button
                onClick={startWatching}
                className={cn(
                  "flex items-center gap-2 px-4 py-2.5 rounded-xl font-semibold text-sm uppercase tracking-wider",
                  "user-gradient text-on-primary-container shadow-lg shadow-primary/20",
                  "hover:shadow-primary/30 hover:scale-105 hover:brightness-110",
                  "active:scale-95 transition-all duration-300"
                )}
              >
                <MaterialIcon icon="play_arrow" className="text-base" filled />
                Watch
              </button>
            )}
            <button
              onClick={exportJson}
              disabled={events.length === 0}
              className={cn(
                "flex items-center gap-2 px-4 py-2.5 rounded-xl font-medium text-sm",
                "bg-surface-container-high text-on-surface border border-outline-variant/20",
                "hover:bg-surface-container-highest hover:scale-105 hover:border-outline-variant/40",
                "active:scale-95 transition-all duration-300",
                "disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
              )}
            >
              <MaterialIcon icon="download" className="text-base" />
              Export
            </button>
            <button
              onClick={clearLogs}
              disabled={events.length === 0}
              className={cn(
                "flex items-center gap-2 px-4 py-2.5 rounded-xl font-medium text-sm",
                "text-on-surface-variant hover:text-error hover:bg-surface-container-high hover:scale-105",
                "active:scale-95 transition-all duration-300",
                "disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
              )}
            >
              <MaterialIcon icon="delete" className="text-base" />
              Clear
            </button>
            {langsmithUiUrl && (
              <button
                onClick={() => window.open(langsmithUiUrl, '_blank', 'noopener,noreferrer')}
                className={cn(
                  "flex items-center gap-2 px-4 py-2.5 rounded-xl font-medium text-sm",
                  "bg-surface-container-high text-on-surface border border-outline-variant/20",
                  "hover:bg-surface-container-highest hover:scale-105 hover:border-outline-variant/40",
                  "active:scale-95 transition-all duration-300"
                )}
              >
                <MaterialIcon icon="open_in_new" className="text-base" />
                LangSmith Home
              </button>
            )}
            {langsmithDashboardUrl && (
              <button
                onClick={() => window.open(langsmithDashboardUrl, '_blank', 'noopener,noreferrer')}
                className={cn(
                  "flex items-center gap-2 px-4 py-2.5 rounded-xl font-medium text-sm",
                  "bg-surface-container-high text-on-surface border border-outline-variant/20",
                  "hover:bg-surface-container-highest hover:scale-105 hover:border-outline-variant/40",
                  "active:scale-95 transition-all duration-300"
                )}
              >
                <MaterialIcon icon="monitoring" className="text-base" />
                Monitor
              </button>
            )}
            {traceSearchUrl && (
              <button
                onClick={async () => {
                  await copyText(traceId || '')
                  window.open(traceSearchUrl, '_blank', 'noopener,noreferrer')
                }}
                className={cn(
                  "flex items-center gap-2 px-4 py-2.5 rounded-xl font-medium text-sm",
                  "bg-primary/10 text-primary border border-primary/30",
                  "hover:bg-primary/15 hover:scale-105 active:scale-95 transition-all duration-300"
                )}
                title="Opens LangSmith monitor and copies trace ID"
              >
                <MaterialIcon icon="account_tree" className="text-base" />
                Open Trace
              </button>
            )}
            {runSearchUrl && (
              <button
                onClick={async () => {
                  await copyText(rootRunId || '')
                  window.open(runSearchUrl, '_blank', 'noopener,noreferrer')
                }}
                className={cn(
                  "flex items-center gap-2 px-4 py-2.5 rounded-xl font-medium text-sm",
                  "bg-secondary/10 text-secondary border border-secondary/30",
                  "hover:bg-secondary/15 hover:scale-105 active:scale-95 transition-all duration-300"
                )}
                title="Opens LangSmith monitor and copies root run ID"
              >
                <MaterialIcon icon="fingerprint" className="text-base" />
                Open Run
              </button>
            )}
            {langsmithDashboardUrl && (
              <button
                onClick={() => setShowEmbeddedDashboard((v) => !v)}
                className={cn(
                  "flex items-center gap-2 px-4 py-2.5 rounded-xl font-medium text-sm",
                  showEmbeddedDashboard
                    ? "bg-secondary/10 text-secondary border border-secondary/30"
                    : "bg-surface-container-high text-on-surface border border-outline-variant/20",
                  "hover:scale-105 active:scale-95 transition-all duration-300"
                )}
              >
                <MaterialIcon icon="web_asset" className="text-base" />
                {showEmbeddedDashboard ? 'Hide Embed' : 'Embed Dashboard'}
              </button>
            )}
          </div>
        </div>
        {(traceId || rootRunId) && (
          <div className="mt-4 pt-4 border-t border-outline-variant/15 flex flex-wrap items-center gap-3 text-xs">
            {traceId && (
              <div className="inline-flex items-center gap-2">
                <button
                  onClick={() => copyText(traceId)}
                  className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface-container-high border border-outline-variant/20 hover:bg-surface-container-highest transition-colors"
                  title={traceId}
                >
                  <MaterialIcon icon="account_tree" className="text-sm" />
                  <span className="font-mono">Trace: {traceId.slice(0, 10)}...</span>
                  <MaterialIcon icon="content_copy" className="text-sm" />
                </button>
                {traceSearchUrl && (
                  <button
                    onClick={() => window.open(traceSearchUrl, '_blank', 'noopener,noreferrer')}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-primary/10 text-primary border border-primary/30 hover:bg-primary/15 transition-colors"
                  >
                    <MaterialIcon icon="open_in_new" className="text-sm" />
                    Open
                  </button>
                )}
              </div>
            )}
            {rootRunId && (
              <div className="inline-flex items-center gap-2">
                <button
                  onClick={() => copyText(rootRunId)}
                  className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-surface-container-high border border-outline-variant/20 hover:bg-surface-container-highest transition-colors"
                  title={rootRunId}
                >
                  <MaterialIcon icon="fingerprint" className="text-sm" />
                  <span className="font-mono">Run: {rootRunId.slice(0, 10)}...</span>
                  <MaterialIcon icon="content_copy" className="text-sm" />
                </button>
                {runSearchUrl && (
                  <button
                    onClick={() => window.open(runSearchUrl, '_blank', 'noopener,noreferrer')}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-secondary/10 text-secondary border border-secondary/30 hover:bg-secondary/15 transition-colors"
                  >
                    <MaterialIcon icon="open_in_new" className="text-sm" />
                    Open
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {showEmbeddedDashboard && langsmithDashboardUrl && (
        <div className={cn(
          "rounded-2xl border border-outline-variant/20 bg-surface-container-low shadow-xl overflow-hidden"
        )}>
          <div className="px-4 py-3 border-b border-outline-variant/15 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm font-semibold text-primary">
              <MaterialIcon icon="monitoring" className="text-base" />
              Embedded LangSmith Dashboard
            </div>
            <button
              onClick={() => window.open(langsmithDashboardUrl, '_blank', 'noopener,noreferrer')}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs bg-surface-container-high border border-outline-variant/20 hover:bg-surface-container-highest"
            >
              <MaterialIcon icon="open_in_new" className="text-sm" />
              Open in New Tab
            </button>
          </div>
          <iframe
            src={langsmithDashboardUrl}
            title="LangSmith Dashboard"
            className="w-full h-[560px] bg-white"
            loading="lazy"
            referrerPolicy="no-referrer"
          />
          <div className="px-4 py-2 text-[11px] text-on-surface-variant border-t border-outline-variant/10">
            If embedding is blocked by provider security headers, use "Open in New Tab".
          </div>
        </div>
      )}

      {/* Events Table */}
      <div className={cn(
        "flex-1 overflow-hidden rounded-2xl border border-outline-variant/20",
        "bg-surface-container-low shadow-xl"
      )}>
        {filtered.length > 150 ? (
          <div>
            <div className={cn(
              "grid grid-cols-[48px_100px_80px_140px_80px_1fr_70px_32px] gap-3 px-4 py-3",
              "border-b border-outline-variant/10 bg-surface-container-high/50",
              "text-[10px] font-semibold text-on-surface-variant uppercase tracking-wider"
            )}>
              <div>#</div><div>Time</div><div>Type</div><div>Node / Tool</div><div>Status</div><div>Details</div><div className="text-right">Speed</div><div />
            </div>
            <FixedSizeList height={460} width="100%" itemCount={filtered.length} itemSize={48} itemData={{ rows: filtered }}>
              {Row}
            </FixedSizeList>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className={cn(
                "bg-surface-container-high/50 border-b border-outline-variant/10 sticky top-0 z-10"
              )}>
                <tr>
                  <th className="text-left px-4 py-3 text-[10px] font-semibold text-on-surface-variant uppercase tracking-wider w-12">#</th>
                  <th className="text-left px-4 py-3 text-[10px] font-semibold text-on-surface-variant uppercase tracking-wider w-28">Time</th>
                  <th className="text-left px-4 py-3 text-[10px] font-semibold text-on-surface-variant uppercase tracking-wider w-24">Type</th>
                  <th className="text-left px-4 py-3 text-[10px] font-semibold text-on-surface-variant uppercase tracking-wider w-36">Node / Tool</th>
                  <th className="text-left px-4 py-3 text-[10px] font-semibold text-on-surface-variant uppercase tracking-wider w-24">Status</th>
                  <th className="text-left px-4 py-3 text-[10px] font-semibold text-on-surface-variant uppercase tracking-wider">Details</th>
                  <th className="text-right px-4 py-3 text-[10px] font-semibold text-on-surface-variant uppercase tracking-wider w-20">Speed</th>
                  <th className="px-4 py-3 w-10" />
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant/10">
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-16 text-center">
                      <div className="flex flex-col items-center gap-3">
                        <div className="w-12 h-12 rounded-2xl bg-surface-container-high flex items-center justify-center">
                          <MaterialIcon icon="radio_button_checked" className="text-3xl text-on-surface-variant/30" />
                        </div>
                        <p className="text-sm text-on-surface-variant">
                          {isWatching ? 'Waiting for events… trigger a workflow execution.' : 'No events yet. Click "Watch" to start.'}
                        </p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  filtered.map((ev, idx) => (
                    <>
                      <tr key={ev.id} className="hover:bg-surface-container-high/50 transition-colors duration-200">
                        <td className="px-4 py-3 text-[10px] text-on-surface-variant/50 tabular-nums font-mono">{idx + 1}</td>
                        <td className="px-4 py-3 text-[10px] text-on-surface-variant tabular-nums font-mono">{fmtTime(ev.timestamp)}</td>
                        <td className="px-4 py-3"><TypeBadge type={ev.event_type} /></td>
                        <td className="px-4 py-3 text-xs font-mono font-medium text-on-surface truncate max-w-[140px]">{ev.label || ev.nodeId}</td>
                        <td className="px-4 py-3"><StatusBadge status={ev.status} /></td>
                        <td className="px-4 py-3 text-xs text-on-surface-variant truncate max-w-[280px]">{ev.details}</td>
                        <td className="px-4 py-3 text-xs text-on-surface-variant/70 tabular-nums text-right font-mono">{ev.duration_ms ?? '—'}</td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => setExpanded(expanded === ev.id ? null : ev.id)}
                            className={cn(
                              "p-1 rounded-md hover:bg-surface-container-highest transition-colors duration-200",
                              "active:scale-95"
                            )}
                          >
                            <MaterialIcon
                              icon={expanded === ev.id ? "expand_more" : "chevron_right"}
                              className="text-base text-on-surface-variant"
                            />
                          </button>
                        </td>
                      </tr>
                      {expanded === ev.id && (
                        <tr key={`${ev.id}-expanded`}>
                          <td colSpan={8} className="px-4 py-4 bg-surface-container-high/30">
                            {(ev.trace_id || ev.run_id || ev.parent_run_id || ev.root_run_id || ev.project) && (
                              <div className="mb-3 grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px]">
                                {ev.project && (
                                  <div className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-container-high border border-outline-variant/20">
                                    <MaterialIcon icon="folder" className="text-sm" />
                                    <span className="text-on-surface-variant">Project:</span>
                                    <span className="font-mono text-on-surface">{ev.project}</span>
                                  </div>
                                )}
                                {ev.trace_id && (
                                  <button
                                    onClick={() => copyText(ev.trace_id ?? '')}
                                    className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-container-high border border-outline-variant/20 hover:bg-surface-container-highest"
                                    title={ev.trace_id}
                                  >
                                    <MaterialIcon icon="account_tree" className="text-sm" />
                                    <span className="text-on-surface-variant">Trace ID:</span>
                                    <span className="font-mono text-on-surface">{ev.trace_id.slice(0, 16)}...</span>
                                    <MaterialIcon icon="content_copy" className="text-sm" />
                                  </button>
                                )}
                                {ev.run_id && (
                                  <button
                                    onClick={() => copyText(ev.run_id ?? '')}
                                    className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-container-high border border-outline-variant/20 hover:bg-surface-container-highest"
                                    title={ev.run_id}
                                  >
                                    <MaterialIcon icon="fingerprint" className="text-sm" />
                                    <span className="text-on-surface-variant">Run ID:</span>
                                    <span className="font-mono text-on-surface">{ev.run_id.slice(0, 16)}...</span>
                                    <MaterialIcon icon="content_copy" className="text-sm" />
                                  </button>
                                )}
                                {ev.parent_run_id && (
                                  <button
                                    onClick={() => copyText(ev.parent_run_id ?? '')}
                                    className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-container-high border border-outline-variant/20 hover:bg-surface-container-highest"
                                    title={ev.parent_run_id}
                                  >
                                    <MaterialIcon icon="call_split" className="text-sm" />
                                    <span className="text-on-surface-variant">Parent Run:</span>
                                    <span className="font-mono text-on-surface">{ev.parent_run_id.slice(0, 16)}...</span>
                                    <MaterialIcon icon="content_copy" className="text-sm" />
                                  </button>
                                )}
                              </div>
                            )}
                            <div className="text-[10px] font-semibold text-on-surface-variant uppercase tracking-wider mb-2">
                              Raw Event Data
                            </div>
                            <pre className={cn(
                              "bg-surface-container-highest text-on-surface px-4 py-3 rounded-xl text-[11px] overflow-x-auto font-mono",
                              "border border-outline-variant/20"
                            )}>
                              {JSON.stringify(ev.raw, null, 2)}
                            </pre>
                          </td>
                        </tr>
                      )}
                    </>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
        <div ref={tableEndRef} />
      </div>

      {/* Status Bar */}
      <div className={cn(
        "rounded-2xl p-4 border border-outline-variant/20",
        "bg-surface-container-low/80 shadow-md"
      )}>
        <div className="flex flex-col gap-3 text-xs text-on-surface-variant xl:flex-row xl:items-start xl:justify-between">
          <div className="flex flex-wrap items-center gap-4 sm:gap-5">
            {/* Session info */}
            <div className="flex items-center gap-2">
              <MaterialIcon icon="fingerprint" className="text-base" />
              <span className="font-mono text-[10px]">Session: {getChatSessionId().slice(0, 8)}...</span>
            </div>
            
            {/* Backend status */}
            {backendStatus && (
              <>
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "w-2 h-2 rounded-full",
                    backendStatus.eventAvailable ? "bg-[hsl(var(--status-vfr))]" : "bg-error"
                  )} />
                  <span>Events: {backendStatus.eventBackend} ({backendStatus.trackedSessions} sessions)</span>
                </div>
                
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "w-2 h-2 rounded-full",
                    backendStatus.langsmith ? "bg-[hsl(var(--status-vfr))]" : "bg-on-surface-variant/30"
                  )} />
                  <span>
                    LangSmith: {backendStatus.langsmith ? 'Active' : 'Disabled'}
                    {' '}({backendStatus.langsmithProject})
                  </span>
                </div>

                <div className="flex max-w-full items-center gap-2 sm:max-w-[420px]" title={backendStatus.langsmithEndpoint}>
                  <MaterialIcon icon="link" className="text-base" />
                  <span className="truncate">{backendStatus.langsmithEndpoint}</span>
                </div>

                <div className="flex max-w-full items-center gap-2 sm:max-w-[440px]" title={backendStatus.langsmithMessage}>
                  <MaterialIcon icon="info" className="text-base" />
                  <span className="truncate">{backendStatus.langsmithMessage}</span>
                </div>

                <div className="flex items-center gap-2">
                  <MaterialIcon icon="hub" className="text-base" />
                  <span>
                    Distributed tracing: {backendStatus.tracingMiddlewareEnabled ? 'enabled' : 'not enabled'}
                  </span>
                </div>
              </>
            )}
          </div>
          
          <div className="flex items-center gap-2 text-[10px] xl:justify-end">
            <MaterialIcon icon="info" className="text-base" />
            <span>Events stream from current chat session</span>
          </div>
        </div>
      </div>
    </div>
  )
}
