import { useState, useEffect, useRef, useCallback } from 'react'
import {
  alpha,
  Box,
  Button,
  Chip,
  Divider,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
  useTheme,
} from '@mui/material'
import { streamAgent } from '@/shared/services/streamService'
import MaterialIcon from '@/components/ui/MaterialIcon'

const API_BASE = import.meta.env.VITE_AGENT_API_URL ?? 'http://localhost:8000'
const CHAT_SESSION_KEY = 'chatSessionId'
const LOG_EVENTS_STORAGE_PREFIX = 'chatLogEvents'
const MAX_LOG_EVENTS = 5000

// Get the same session ID used by the chat
function getChatSessionId(): string {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') {
    return 'default'
  }

  const existing = localStorage.getItem(CHAT_SESSION_KEY)
  if (existing) return existing

  const random = Math.random().toString(36).slice(2, 10)
  const created = `web-${Date.now().toString(36)}-${random}`
  localStorage.setItem(CHAT_SESSION_KEY, created)
  return created
}

function getLogEventsStorageKey(sessionId: string): string {
  return `${LOG_EVENTS_STORAGE_PREFIX}:${sessionId}`
}

function serializeEventForStorage(event: LogEvent): Record<string, unknown> {
  return {
    ...event,
    timestamp: event.timestamp.toISOString(),
  }
}

function deserializeEventFromStorage(raw: any): LogEvent {
  return {
    ...raw,
    timestamp: new Date(raw.timestamp),
    raw: (raw.raw && typeof raw.raw === 'object') ? raw.raw : {},
  }
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

const TYPE_CONFIG: Record<string, { icon: string; color: 'primary' | 'secondary' | 'success' | 'error' | 'default'; label: string }> = {
  node: { icon: 'circle', color: 'secondary', label: 'Node' },
  trace_context: { icon: 'hub', color: 'primary', label: 'Trace' },
  routing_decision: { icon: 'alt_route', color: 'primary', label: 'Route' },
  tool: { icon: 'build', color: 'success', label: 'Tool' },
  reasoning: { icon: 'psychology', color: 'secondary', label: 'Think' },
  internal: { icon: 'settings', color: 'default', label: 'Internal' },
  error: { icon: 'error', color: 'error', label: 'Error' },
}

const STATUS_COLORS: Record<string, 'default' | 'primary' | 'success' | 'error'> = {
  started: 'primary',
  running: 'primary',
  completed: 'success',
  failed: 'error',
  error: 'error',
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
    <Chip
      size="small"
      color={config.color}
      variant={config.color === 'default' ? 'outlined' : 'filled'}
      icon={<MaterialIcon icon={config.icon} filled />}
      label={config.label}
      sx={{ height: 24 }}
    />
  )
}

function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status] ?? 'default'
  return (
    <Chip size="small" color={color} variant={color === 'default' ? 'outlined' : 'filled'} label={status} sx={{ height: 24 }} />
  )
}

export default function LogsView() {
  const theme = useTheme()
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
    if (typeof window === 'undefined' || typeof localStorage === 'undefined') return

    try {
      const sessionId = getChatSessionId()
      const stored = localStorage.getItem(getLogEventsStorageKey(sessionId))
      if (!stored) return

      const parsed = JSON.parse(stored)
      if (!Array.isArray(parsed)) return

      const restored = parsed.map(deserializeEventFromStorage).filter((event) => !Number.isNaN(event.timestamp.getTime()))
      setEvents(restored)

      const signatures = new Set<string>()
      for (const event of restored) {
        signatures.add(eventSignature(event.raw))
      }
      seenEventSignaturesRef.current = signatures
    } catch {
      // Ignore invalid or stale persisted logs.
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined' || typeof localStorage === 'undefined') return

    try {
      const sessionId = getChatSessionId()
      localStorage.setItem(
        getLogEventsStorageKey(sessionId),
        JSON.stringify(events.map(serializeEventForStorage))
      )
    } catch {
      // Ignore storage failures.
    }
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
          setEvents((prev) => {
            const next = [...prev, event]
            if (next.length <= MAX_LOG_EVENTS) return next
            return next.slice(-MAX_LOG_EVENTS)
          })
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
    if (typeof window !== 'undefined' && typeof localStorage !== 'undefined') {
      localStorage.removeItem(getLogEventsStorageKey(getChatSessionId()))
    }
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

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, p: { xs: 2, md: 3 }, height: '100%' }}>
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: 'column', lg: 'row' }} spacing={2} justifyContent="space-between">
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <MaterialIcon icon="analytics" />
                <Typography variant="h6" fontWeight={700}>Event Trace</Typography>
                {isWatching && <Chip color="secondary" size="small" label="Live" />}
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.4 }}>
                {events.length} event{events.length !== 1 ? 's' : ''} captured
              </Typography>

              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1.5 }}>
                {FILTERS.map((f) => (
                  <Chip
                    key={f.key}
                    label={`${f.label} (${f.count})`}
                    color={filter === f.key ? 'primary' : 'default'}
                    variant={filter === f.key ? 'filled' : 'outlined'}
                    onClick={() => setFilter(f.key)}
                    clickable
                  />
                ))}
              </Stack>
            </Box>

            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Button
                variant={isWatching ? 'outlined' : 'contained'}
                color={isWatching ? 'error' : 'primary'}
                onClick={isWatching ? stopWatching : startWatching}
                startIcon={<MaterialIcon icon={isWatching ? 'stop' : 'play_arrow'} filled />}
              >
                {isWatching ? 'Stop' : 'Watch'}
              </Button>
              <Button variant="outlined" onClick={exportJson} disabled={events.length === 0} startIcon={<MaterialIcon icon="download" />}>
                Export
              </Button>
              <Button variant="outlined" color="error" onClick={clearLogs} disabled={events.length === 0} startIcon={<MaterialIcon icon="delete" />}>
                Clear
              </Button>
              {langsmithUiUrl && (
                <Button variant="outlined" onClick={() => window.open(langsmithUiUrl, '_blank', 'noopener,noreferrer')} startIcon={<MaterialIcon icon="open_in_new" />}>
                  LangSmith Home
                </Button>
              )}
              {langsmithDashboardUrl && (
                <Button variant="outlined" onClick={() => window.open(langsmithDashboardUrl, '_blank', 'noopener,noreferrer')} startIcon={<MaterialIcon icon="monitoring" />}>
                  Monitor
                </Button>
              )}
              {traceSearchUrl && (
                <Button
                  variant="outlined"
                  color="primary"
                  onClick={async () => {
                    await copyText(traceId || '')
                    window.open(traceSearchUrl, '_blank', 'noopener,noreferrer')
                  }}
                  startIcon={<MaterialIcon icon="account_tree" />}
                >
                  Open Trace
                </Button>
              )}
              {runSearchUrl && (
                <Button
                  variant="outlined"
                  color="secondary"
                  onClick={async () => {
                    await copyText(rootRunId || '')
                    window.open(runSearchUrl, '_blank', 'noopener,noreferrer')
                  }}
                  startIcon={<MaterialIcon icon="fingerprint" />}
                >
                  Open Run
                </Button>
              )}
              {langsmithDashboardUrl && (
                <Button
                  variant={showEmbeddedDashboard ? 'contained' : 'outlined'}
                  color="secondary"
                  onClick={() => setShowEmbeddedDashboard((v) => !v)}
                  startIcon={<MaterialIcon icon="web_asset" />}
                >
                  {showEmbeddedDashboard ? 'Hide Embed' : 'Embed Dashboard'}
                </Button>
              )}
            </Stack>
          </Stack>

          {(traceId || rootRunId) && (
            <>
              <Divider />
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                {traceId && (
                  <Chip
                    variant="outlined"
                    icon={<MaterialIcon icon="account_tree" />}
                    label={`Trace: ${traceId.slice(0, 12)}...`}
                    onClick={() => copyText(traceId)}
                    clickable
                  />
                )}
                {rootRunId && (
                  <Chip
                    variant="outlined"
                    icon={<MaterialIcon icon="fingerprint" />}
                    label={`Run: ${rootRunId.slice(0, 12)}...`}
                    onClick={() => copyText(rootRunId)}
                    clickable
                  />
                )}
              </Stack>
            </>
          )}
        </Stack>
      </Paper>

      {showEmbeddedDashboard && langsmithDashboardUrl && (
        <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
          <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ px: 2, py: 1.2, borderBottom: `1px solid ${theme.palette.divider}` }}>
            <Stack direction="row" spacing={1} alignItems="center">
              <MaterialIcon icon="monitoring" />
              <Typography variant="subtitle2" fontWeight={700}>Embedded LangSmith Dashboard</Typography>
            </Stack>
            <Button
              size="small"
              variant="outlined"
              onClick={() => window.open(langsmithDashboardUrl, '_blank', 'noopener,noreferrer')}
              startIcon={<MaterialIcon icon="open_in_new" />}
            >
              Open in New Tab
            </Button>
          </Stack>
          <Box component="iframe" src={langsmithDashboardUrl} title="LangSmith Dashboard" sx={{ width: '100%', height: 560, border: 'none', bgcolor: '#fff' }} loading="lazy" referrerPolicy="no-referrer" />
          <Typography variant="caption" color="text.secondary" sx={{ px: 2, py: 1.1, display: 'block' }}>
            If embedding is blocked by provider security headers, use Open in New Tab.
          </Typography>
        </Paper>
      )}

      <Paper variant="outlined" sx={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <TableContainer sx={{ height: '100%' }}>
          <Table stickyHeader size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 52 }}>#</TableCell>
                <TableCell sx={{ width: 120 }}>Time</TableCell>
                <TableCell sx={{ width: 120 }}>Type</TableCell>
                <TableCell sx={{ width: 170 }}>Node / Tool</TableCell>
                <TableCell sx={{ width: 120 }}>Status</TableCell>
                <TableCell>Details</TableCell>
                <TableCell align="right" sx={{ width: 90 }}>Speed</TableCell>
                <TableCell sx={{ width: 50 }} />
              </TableRow>
            </TableHead>

            <TableBody>
              {filtered.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} sx={{ py: 9 }}>
                    <Stack alignItems="center" spacing={1.2}>
                      <MaterialIcon icon="radio_button_checked" />
                      <Typography variant="body2" color="text.secondary">
                        {isWatching ? 'Waiting for events. Trigger a workflow execution.' : 'No events yet. Click Watch to start.'}
                      </Typography>
                    </Stack>
                  </TableCell>
                </TableRow>
              )}

              {filtered.flatMap((ev, idx) => {
                const rows = [
                  <TableRow key={ev.id} hover>
                    <TableCell sx={{ fontFamily: 'monospace', fontSize: 12, color: 'text.secondary' }}>{idx + 1}</TableCell>
                    <TableCell sx={{ fontFamily: 'monospace', fontSize: 12 }}>{fmtTime(ev.timestamp)}</TableCell>
                    <TableCell><TypeBadge type={ev.event_type} /></TableCell>
                    <TableCell sx={{ fontFamily: 'monospace', fontWeight: 600, maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {ev.label || ev.nodeId}
                    </TableCell>
                    <TableCell><StatusBadge status={ev.status} /></TableCell>
                    <TableCell sx={{ maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'text.secondary' }}>
                      {ev.details}
                    </TableCell>
                    <TableCell align="right" sx={{ fontFamily: 'monospace' }}>{ev.duration_ms ?? '—'}</TableCell>
                    <TableCell>
                      <Tooltip title={expanded === ev.id ? 'Collapse' : 'Expand'}>
                        <IconButton size="small" onClick={() => setExpanded(expanded === ev.id ? null : ev.id)}>
                          <MaterialIcon icon={expanded === ev.id ? 'expand_more' : 'chevron_right'} />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>,
                ]

                if (expanded === ev.id) {
                  rows.push(
                    <TableRow key={`${ev.id}-expanded`}>
                      <TableCell colSpan={8} sx={{ bgcolor: alpha(theme.palette.action.hover, 0.5) }}>
                        <Stack spacing={1}>
                          {(ev.trace_id || ev.run_id || ev.parent_run_id || ev.root_run_id || ev.project) && (
                            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                              {ev.project && <Chip variant="outlined" label={`Project: ${ev.project}`} />}
                              {ev.trace_id && <Chip variant="outlined" label={`Trace: ${ev.trace_id.slice(0, 16)}...`} onClick={() => copyText(ev.trace_id ?? '')} clickable />}
                              {ev.run_id && <Chip variant="outlined" label={`Run: ${ev.run_id.slice(0, 16)}...`} onClick={() => copyText(ev.run_id ?? '')} clickable />}
                              {ev.parent_run_id && <Chip variant="outlined" label={`Parent: ${ev.parent_run_id.slice(0, 16)}...`} onClick={() => copyText(ev.parent_run_id ?? '')} clickable />}
                            </Stack>
                          )}

                          <Typography variant="caption" fontWeight={700} color="text.secondary">Raw Event Data</Typography>
                          <Paper variant="outlined" sx={{ p: 1.2, bgcolor: alpha(theme.palette.background.paper, 0.7) }}>
                            <Typography component="pre" variant="caption" sx={{ m: 0, whiteSpace: 'pre-wrap', overflowX: 'auto', fontFamily: 'monospace' }}>
                              {JSON.stringify(ev.raw, null, 2)}
                            </Typography>
                          </Paper>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  )
                }

                return rows
              })}
            </TableBody>
          </Table>
        </TableContainer>
        <div ref={tableEndRef} />
      </Paper>

      <Paper variant="outlined" sx={{ p: 1.5 }}>
        <Stack direction={{ xs: 'column', xl: 'row' }} spacing={1.2} justifyContent="space-between">
          <Stack direction="row" spacing={1.5} flexWrap="wrap" useFlexGap alignItems="center">
            <Chip variant="outlined" icon={<MaterialIcon icon="fingerprint" />} label={`Session: ${getChatSessionId().slice(0, 8)}...`} />

            {backendStatus && (
              <>
                <Chip
                  variant="outlined"
                  color={backendStatus.eventAvailable ? 'success' : 'error'}
                  label={`Events: ${backendStatus.eventBackend} (${backendStatus.trackedSessions})`}
                />
                <Chip
                  variant="outlined"
                  color={backendStatus.langsmith ? 'success' : 'default'}
                  label={`LangSmith: ${backendStatus.langsmith ? 'Active' : 'Disabled'} (${backendStatus.langsmithProject})`}
                />
                <Chip variant="outlined" icon={<MaterialIcon icon="link" />} label={backendStatus.langsmithEndpoint} />
                <Chip variant="outlined" icon={<MaterialIcon icon="hub" />} label={`Distributed tracing: ${backendStatus.tracingMiddlewareEnabled ? 'enabled' : 'disabled'}`} />
              </>
            )}
          </Stack>

          <Typography variant="caption" color="text.secondary" sx={{ alignSelf: { xl: 'center' } }}>
            Events stream from current chat session
          </Typography>
        </Stack>
      </Paper>
    </Box>
  )
}
