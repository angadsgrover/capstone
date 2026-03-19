import { useState, useEffect, useRef, useCallback } from 'react'
import { FixedSizeList, type ListChildComponentProps } from 'react-window'
import { streamAgent } from '@/shared/services/streamService'
import { Button } from '@/components/ui/button'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Card, CardContent, CardTitle, CardDescription } from '@/components/ui/card'

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

const STATUS_BADGE: Record<string, BadgeProps['variant']> = {
  started: 'info',
  running: 'info',
  completed: 'success',
  failed: 'destructive',
  error: 'destructive',
}

const TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  node: { bg: 'bg-blue-100 dark:bg-blue-900/40', text: 'text-blue-700 dark:text-blue-300', label: 'Node' },
  routing_decision: { bg: 'bg-purple-100 dark:bg-purple-900/40', text: 'text-purple-700 dark:text-purple-300', label: 'Route' },
  tool: { bg: 'bg-amber-100 dark:bg-amber-900/40', text: 'text-amber-700 dark:text-amber-300', label: 'Tool' },
  reasoning: { bg: 'bg-emerald-100 dark:bg-emerald-900/40', text: 'text-emerald-700 dark:text-emerald-300', label: 'Think' },
  internal: { bg: 'bg-zinc-100 dark:bg-zinc-800', text: 'text-zinc-500 dark:text-zinc-400', label: 'Internal' },
  error: { bg: 'bg-red-100 dark:bg-red-900/40', text: 'text-red-700 dark:text-red-300', label: 'Error' },
}

type FilterType = 'all' | 'node' | 'tool' | 'routing_decision' | 'reasoning' | 'internal'

function fmtTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
    `.${String(d.getMilliseconds()).padStart(3, '0')}`
}

function TypeBadge({ type }: { type: string }) {
  const s = TYPE_STYLES[type] ?? TYPE_STYLES.node
  return <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold ${s.bg} ${s.text}`}>{s.label}</span>
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
          // ignore non-JSON keepalive payloads
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

  const Row = ({ index, style, data }: ListChildComponentProps<{ rows: LogEvent[] }>) => {
    const ev = data.rows[index]
    return (
      <div
        style={style}
        className="border-b border-border px-3 py-2.5 text-xs grid grid-cols-[48px_120px_92px_160px_100px_1fr_80px_24px] gap-2 items-center hover:bg-muted/40"
      >
        <div className="text-[10px] text-muted-foreground/60 tabular-nums">{index + 1}</div>
        <div className="text-[10px] text-muted-foreground tabular-nums whitespace-nowrap font-mono">{fmtTime(ev.timestamp)}</div>
        <div><TypeBadge type={ev.event_type} /></div>
        <div className="font-mono truncate">{ev.label || ev.nodeId}</div>
        <div><Badge variant={STATUS_BADGE[ev.status] ?? 'secondary'} className="text-[10px]">{ev.status}</Badge></div>
        <div className="truncate">{ev.details}</div>
        <div className="text-right tabular-nums">{ev.duration_ms !== undefined ? ev.duration_ms.toLocaleString() : '—'}</div>
        <button
          type="button"
          className="text-muted-foreground text-[10px]"
          onClick={() => setExpanded(expanded === ev.id ? null : ev.id)}
        >
          {expanded === ev.id ? '▲' : '▼'}
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-wrap items-start gap-3">
            <div className="flex-1 min-w-0">
              <CardTitle className="text-base">Event Trace</CardTitle>
              <CardDescription className="mt-0.5 flex flex-wrap items-center gap-2">
                <span>{events.length} event{events.length !== 1 ? 's' : ''}</span>
                {isWatching && (
                  <Badge variant="success" className="gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
                    Live
                  </Badge>
                )}
              </CardDescription>

              <div className="flex flex-wrap gap-1.5 mt-3">
                {(['all', 'node', 'routing_decision', 'tool', 'reasoning', 'internal'] as FilterType[]).map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                      filter === f
                        ? 'bg-foreground text-background border-foreground'
                        : 'bg-muted/50 text-muted-foreground border-transparent hover:border-border'
                    }`}
                  >
                    {f === 'all' ? `All (${events.length})` :
                      f === 'routing_decision' ? `Route (${counts.routing_decision ?? 0})` :
                        f === 'node' ? `Nodes (${counts.node ?? 0})` :
                          f === 'tool' ? `Tools (${counts.tool ?? 0})` :
                            f === 'reasoning' ? `Think (${counts.reasoning ?? 0})` :
                              `Internal (${counts.internal ?? 0})`}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex gap-2 flex-wrap">
              {isWatching
                ? <Button variant="destructive" size="sm" onClick={stopWatching}>Stop</Button>
                : <Button size="sm" onClick={startWatching}>Watch Events</Button>}
              <Button variant="outline" size="sm" onClick={exportJson} disabled={events.length === 0}>Export JSON</Button>
              <Button variant="ghost" size="sm" onClick={clearLogs} disabled={events.length === 0} className="text-muted-foreground hover:text-destructive">
                Clear
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="overflow-hidden">
        {filtered.length > 150 ? (
          <div>
            <div className="grid grid-cols-[48px_120px_92px_160px_100px_1fr_80px_24px] gap-2 px-3 py-2 border-b bg-muted/50 text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
              <div>#</div><div>Time</div><div>Type</div><div>Node / Tool</div><div>Status</div><div>Details</div><div className="text-right">ms</div><div />
            </div>
            <FixedSizeList height={460} width="100%" itemCount={filtered.length} itemSize={42} itemData={{ rows: filtered }}>
              {Row}
            </FixedSizeList>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 border-b sticky top-0 z-10">
                <tr>
                  <th className="text-left px-3 py-3 text-[10px] font-semibold text-muted-foreground uppercase tracking-wide whitespace-nowrap">#</th>
                  <th className="text-left px-3 py-3 text-[10px] font-semibold text-muted-foreground uppercase tracking-wide whitespace-nowrap">Time</th>
                  <th className="text-left px-3 py-3 text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">Type</th>
                  <th className="text-left px-3 py-3 text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">Node / Tool</th>
                  <th className="text-left px-3 py-3 text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">Status</th>
                  <th className="text-left px-3 py-3 text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">Details</th>
                  <th className="text-right px-3 py-3 text-[10px] font-semibold text-muted-foreground uppercase tracking-wide whitespace-nowrap">ms</th>
                  <th className="px-3 py-3 w-8" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-xs text-muted-foreground">
                      {isWatching ? 'Waiting for events… trigger a workflow execution.' : 'No events. Click "Watch Events" then run a workflow.'}
                    </td>
                  </tr>
                ) : (
                  filtered.map((ev, idx) => (
                    <tr key={ev.id} className="hover:bg-muted/40">
                      <td className="px-3 py-2.5 text-[10px] text-muted-foreground/60 tabular-nums">{idx + 1}</td>
                      <td className="px-3 py-2.5 text-[10px] text-muted-foreground tabular-nums whitespace-nowrap font-mono">{fmtTime(ev.timestamp)}</td>
                      <td className="px-3 py-2.5"><TypeBadge type={ev.event_type} /></td>
                      <td className="px-3 py-2.5 text-xs font-mono text-foreground max-w-[140px] truncate">{ev.label || ev.nodeId}</td>
                      <td className="px-3 py-2.5"><Badge variant={STATUS_BADGE[ev.status] ?? 'secondary'} className="text-[10px]">{ev.status}</Badge></td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground max-w-[260px] truncate">{ev.details}</td>
                      <td className="px-3 py-2.5 text-xs text-muted-foreground tabular-nums text-right whitespace-nowrap">{ev.duration_ms ?? '—'}</td>
                      <td />
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
        <div ref={tableEndRef} />
      </Card>
    </div>
  )
}

