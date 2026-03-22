import { useState, useEffect, useRef, useCallback } from 'react'
import { FixedSizeList, type ListChildComponentProps } from 'react-window'
import { streamAgent } from '@/shared/services/streamService'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardTitle, CardDescription } from '@/components/ui/card'
import {
  Play, Square, Download, Trash2, ChevronDown, ChevronRight,
  Radio, Circle, GitBranch, Wrench, Brain, Cog, AlertCircle,
  Clock, Zap
} from 'lucide-react'

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

const TYPE_CONFIG: Record<string, { icon: typeof Circle; color: string; label: string; variant: 'default' | 'info' | 'purple' | 'warning' | 'success' | 'secondary' | 'destructive' }> = {
  node: { icon: Circle, color: 'text-blue-500', label: 'Node', variant: 'info' },
  routing_decision: { icon: GitBranch, color: 'text-purple-500', label: 'Route', variant: 'purple' },
  tool: { icon: Wrench, color: 'text-amber-500', label: 'Tool', variant: 'warning' },
  reasoning: { icon: Brain, color: 'text-emerald-500', label: 'Think', variant: 'success' },
  internal: { icon: Cog, color: 'text-slate-400', label: 'Internal', variant: 'secondary' },
  error: { icon: AlertCircle, color: 'text-red-500', label: 'Error', variant: 'destructive' },
}

const STATUS_VARIANT: Record<string, 'default' | 'info' | 'success' | 'destructive' | 'secondary'> = {
  started: 'info',
  running: 'info',
  completed: 'success',
  failed: 'destructive',
  error: 'destructive',
}

type FilterType = 'all' | 'node' | 'tool' | 'routing_decision' | 'reasoning' | 'internal'

function fmtTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
    `.${String(d.getMilliseconds()).padStart(3, '0')}`
}

function TypeBadge({ type }: { type: string }) {
  const config = TYPE_CONFIG[type] ?? TYPE_CONFIG.node
  const Icon = config.icon
  return (
    <Badge variant={config.variant} className="gap-1">
      <Icon className="h-3 w-3" />
      {config.label}
    </Badge>
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
        className="border-b border-slate-200 dark:border-slate-700/50 px-4 py-3 text-xs grid grid-cols-[48px_100px_80px_140px_80px_1fr_70px_32px] gap-3 items-center hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
      >
        <div className="text-[10px] text-slate-400 dark:text-slate-500 tabular-nums font-mono">{index + 1}</div>
        <div className="text-[10px] text-slate-500 dark:text-slate-400 tabular-nums font-mono">{fmtTime(ev.timestamp)}</div>
        <div><TypeBadge type={ev.event_type} /></div>
        <div className="font-mono font-medium text-slate-700 dark:text-slate-200 truncate">{ev.label || ev.nodeId}</div>
        <div><Badge variant={STATUS_VARIANT[ev.status] ?? 'secondary'} size="sm">{ev.status}</Badge></div>
        <div className="text-slate-500 dark:text-slate-400 truncate">{ev.details}</div>
        <div className="text-right tabular-nums font-mono text-slate-400 dark:text-slate-500 flex items-center justify-end gap-1">
          <Zap className="h-3 w-3" />
          {ev.duration_ms !== undefined ? ev.duration_ms.toLocaleString() : '—'}
        </div>
        <button
          type="button"
          className="p-1 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
          onClick={() => setExpanded(expanded === ev.id ? null : ev.id)}
        >
          {expanded === ev.id ? (
            <ChevronDown className="h-4 w-4 text-slate-400" />
          ) : (
            <ChevronRight className="h-4 w-4 text-slate-400" />
          )}
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* Header Card */}
      <Card>
        <CardContent className="pt-5">
          <div className="flex flex-wrap items-start gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 mb-1">
                <CardTitle className="text-lg">Event Trace</CardTitle>
                {isWatching && (
                  <Badge variant="live" className="gap-1.5">
                    <Radio className="h-3 w-3" />
                    Live
                  </Badge>
                )}
              </div>
              <CardDescription className="flex items-center gap-2">
                <Clock className="h-3.5 w-3.5" />
                {events.length} event{events.length !== 1 ? 's' : ''} captured
              </CardDescription>

              {/* Filter chips */}
              <div className="flex flex-wrap gap-2 mt-4">
                {FILTERS.map((f) => (
                  <button
                    key={f.key}
                    onClick={() => setFilter(f.key)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all duration-200 ${
                      filter === f.key
                        ? 'bg-indigo-500 text-white border-indigo-500 shadow-md shadow-indigo-500/25'
                        : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:border-indigo-300 dark:hover:border-indigo-700'
                    }`}
                  >
                    {f.label} ({f.count})
                  </button>
                ))}
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex gap-2 flex-wrap">
              {isWatching ? (
                <Button variant="destructive" size="sm" onClick={stopWatching} className="gap-1.5">
                  <Square className="h-3.5 w-3.5" />
                  Stop
                </Button>
              ) : (
                <Button size="sm" onClick={startWatching} className="gap-1.5">
                  <Play className="h-3.5 w-3.5" />
                  Watch Events
                </Button>
              )}
              <Button variant="outline" size="sm" onClick={exportJson} disabled={events.length === 0} className="gap-1.5">
                <Download className="h-3.5 w-3.5" />
                Export
              </Button>
              <Button variant="ghost" size="sm" onClick={clearLogs} disabled={events.length === 0} className="gap-1.5 text-slate-500 hover:text-red-500">
                <Trash2 className="h-3.5 w-3.5" />
                Clear
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Events Table */}
      <Card className="flex-1 overflow-hidden">
        {filtered.length > 150 ? (
          <div>
            <div className="grid grid-cols-[48px_100px_80px_140px_80px_1fr_70px_32px] gap-3 px-4 py-3 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              <div>#</div><div>Time</div><div>Type</div><div>Node / Tool</div><div>Status</div><div>Details</div><div className="text-right">Speed</div><div />
            </div>
            <FixedSizeList height={460} width="100%" itemCount={filtered.length} itemSize={48} itemData={{ rows: filtered }}>
              {Row}
            </FixedSizeList>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-700 sticky top-0 z-10">
                <tr>
                  <th className="text-left px-4 py-3 text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider w-12">#</th>
                  <th className="text-left px-4 py-3 text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider w-28">Time</th>
                  <th className="text-left px-4 py-3 text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider w-24">Type</th>
                  <th className="text-left px-4 py-3 text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider w-36">Node / Tool</th>
                  <th className="text-left px-4 py-3 text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider w-24">Status</th>
                  <th className="text-left px-4 py-3 text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Details</th>
                  <th className="text-right px-4 py-3 text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider w-20">Speed</th>
                  <th className="px-4 py-3 w-10" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-16 text-center">
                      <div className="flex flex-col items-center gap-3">
                        <div className="w-12 h-12 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
                          <Radio className="h-6 w-6 text-slate-400" />
                        </div>
                        <p className="text-sm text-slate-500 dark:text-slate-400">
                          {isWatching ? 'Waiting for events… trigger a workflow execution.' : 'No events yet. Click "Watch Events" to start.'}
                        </p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  filtered.map((ev, idx) => (
                    <>
                      <tr key={ev.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                        <td className="px-4 py-3 text-[10px] text-slate-400 dark:text-slate-500 tabular-nums font-mono">{idx + 1}</td>
                        <td className="px-4 py-3 text-[10px] text-slate-500 dark:text-slate-400 tabular-nums font-mono">{fmtTime(ev.timestamp)}</td>
                        <td className="px-4 py-3"><TypeBadge type={ev.event_type} /></td>
                        <td className="px-4 py-3 text-xs font-mono font-medium text-slate-700 dark:text-slate-200 truncate max-w-[140px]">{ev.label || ev.nodeId}</td>
                        <td className="px-4 py-3"><Badge variant={STATUS_VARIANT[ev.status] ?? 'secondary'} size="sm">{ev.status}</Badge></td>
                        <td className="px-4 py-3 text-xs text-slate-500 dark:text-slate-400 truncate max-w-[280px]">{ev.details}</td>
                        <td className="px-4 py-3 text-xs text-slate-400 dark:text-slate-500 tabular-nums text-right font-mono">{ev.duration_ms ?? '—'}</td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => setExpanded(expanded === ev.id ? null : ev.id)}
                            className="p-1 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                          >
                            {expanded === ev.id ? (
                              <ChevronDown className="h-4 w-4 text-slate-400" />
                            ) : (
                              <ChevronRight className="h-4 w-4 text-slate-400" />
                            )}
                          </button>
                        </td>
                      </tr>
                      {expanded === ev.id && (
                        <tr key={`${ev.id}-expanded`}>
                          <td colSpan={8} className="px-4 py-4 bg-slate-50 dark:bg-slate-800/30">
                            <div className="text-[10px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2">
                              Raw Event Data
                            </div>
                            <pre className="bg-slate-900 text-slate-100 px-4 py-3 rounded-xl text-[11px] overflow-x-auto font-mono">
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
      </Card>
    </div>
  )
}
