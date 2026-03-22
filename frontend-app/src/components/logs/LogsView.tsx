import { useState, useEffect, useRef, useCallback } from 'react'
import { FixedSizeList, type ListChildComponentProps } from 'react-window'
import { streamAgent } from '@/shared/services/streamService'
import MaterialIcon from '@/components/ui/MaterialIcon'
import { cn } from '@/lib/utils'

const API_BASE = import.meta.env.VITE_AGENT_API_URL ?? 'http://localhost:8000'

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
  raw: Record<string, unknown>
}

const TYPE_CONFIG: Record<string, { icon: string; colorClass: string; bgClass: string; label: string }> = {
  node: { icon: 'circle', colorClass: 'text-secondary', bgClass: 'bg-secondary/10 border-secondary/30', label: 'Node' },
  routing_decision: { icon: 'alt_route', colorClass: 'text-primary', bgClass: 'bg-primary/10 border-primary/30', label: 'Route' },
  tool: { icon: 'build', colorClass: 'text-amber-500', bgClass: 'bg-amber-500/10 border-amber-500/30', label: 'Tool' },
  reasoning: { icon: 'psychology', colorClass: 'text-emerald-500', bgClass: 'bg-emerald-500/10 border-emerald-500/30',  label: 'Think' },
  internal: { icon: 'settings', colorClass: 'text-on-surface-variant/50', bgClass: 'bg-surface-container border-outline-variant/30', label: 'Internal' },
  error: { icon: 'error', colorClass: 'text-error', bgClass: 'bg-error/10 border-error/30', label: 'Error' },
}

const STATUS_COLORS: Record<string, string> = {
  started: 'bg-secondary/10 text-secondary border-secondary/30',
  running: 'bg-secondary/10 text-secondary border-secondary/30',
  completed: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30',
  failed: 'bg-error/10 text-error border-error/30',
  error: 'bg-error/10 text-error border-error/30',
}

type FilterType = 'all' | 'node' | 'tool' | 'routing_decision' | 'reasoning' | 'internal'

function fmtTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
    `.${String(d.getMilliseconds()).padStart(3, '0')}`
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
  const cancelRef = useRef<(() => void) | null>(null)
  const tableEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    tableEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events])

  useEffect(() => () => cancelRef.current?.(), [])

  const startWatching = useCallback(() => {
    if (isWatching) return
    setIsWatching(true)
    cancelRef.current = streamAgent(`${API_BASE}/api/agent/events?session_id=default`, {
      onChunk: (rawData) => {
        try {
          const data = JSON.parse(rawData)
          if (data.__done__) return
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
            raw: data,
          }
          setEvents((prev) => [...prev, event])
        } catch {
          // ignore non-JSON keepalive
        }
      },
      onError: () => setIsWatching(false),
      onComplete: () => setIsWatching(false),
    })
  }, [isWatching])

  const stopWatching = useCallback(() => {
    cancelRef.current?.()
    cancelRef.current = null
    setIsWatching(false)
  }, [])

  const clearLogs = useCallback(() => {
    stopWatching()
    setEvents([])
    setExpanded(null)
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
    { key: 'node', label: 'Nodes', count: counts.node ?? 0 },
    { key: 'routing_decision', label: 'Route', count: counts.routing_decision ?? 0 },
    { key: 'tool', label: 'Tools', count: counts.tool ?? 0 },
    { key: 'reasoning', label: 'Think', count: counts.reasoning ?? 0 },
    { key: 'internal', label: 'Internal', count: counts.internal ?? 0 },
  ]

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
          </div>
        </div>
      </div>

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
    </div>
  )
}
