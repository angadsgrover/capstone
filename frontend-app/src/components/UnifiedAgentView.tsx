import { useState, useRef, useEffect, useCallback } from 'react'
import { toast } from 'sonner'
import { alpha, Box, Button, Chip, CircularProgress, Paper, Stack, Typography, useMediaQuery, useTheme } from '@mui/material'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  Node,
  Edge,
  NodeProps,
  Handle,
  Position,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { useChatStore } from '@/shared/state/chatStore'
import { useWorkflowStore } from '@/shared/state/workflowStore'
import { streamAgent, streamAgentFetch } from '@/shared/services/streamService'
import { useLiveKitVoice } from '@/shared/hooks/useLiveKitVoice'
import { Message } from '@/shared/types/agent'
import MessageBubble from './chat/MessageBubble'
import ChatInput from './chat/ChatInput'
import MaterialIcon from '@/components/ui/MaterialIcon'

const API_BASE = import.meta.env.VITE_AGENT_API_URL
  ?? (import.meta.env.DEV ? 'http://localhost:8000' : window.location.origin)
const CHAT_SESSION_KEY = 'chatSessionId'

function getOrCreateSessionId(): string {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') {
    return 'web-default'
  }
  const existing = localStorage.getItem(CHAT_SESSION_KEY)
  if (existing) return existing
  const random = Math.random().toString(36).slice(2, 10)
  const id = `web-${Date.now().toString(36)}-${random}`
  localStorage.setItem(CHAT_SESSION_KEY, id)
  return id
}

const QUICK_PROMPTS = [
  { text: "What's the weather in Hong Kong?", icon: 'wb_cloudy' },
  { text: "Show METAR for VHHH", icon: 'flight_takeoff' },
  { text: "Any active weather warnings?", icon: 'warning' },
  { text: "Aviation weather for Heathrow", icon: 'bolt' },
]

// ── MD3 Status Colors ─────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, { border: string; bg: string; text: string }> = {
  idle:      { border: 'hsl(var(--outline-variant))', bg: 'hsl(var(--surface-container-low))', text: 'hsl(var(--on-surface-variant))' },
  running:   { border: 'hsl(var(--secondary))', bg: 'hsl(var(--secondary-container) / 0.3)', text: 'hsl(var(--secondary))' },
  completed: { border: 'hsl(var(--status-vfr))', bg: 'hsl(var(--status-vfr) / 0.15)', text: 'hsl(var(--status-vfr))' },
  error:     { border: 'hsl(var(--error))', bg: 'hsl(var(--error-container) / 0.2)', text: 'hsl(var(--error))' },
}
const EDGE_DEFAULT = { stroke: 'hsl(var(--outline-variant) / 0.55)', strokeDasharray: '5 3' }
const EDGE_ACTIVE  = { stroke: 'hsl(var(--secondary))', strokeWidth: 2.5 }
const EDGE_TOOL    = { stroke: 'hsl(var(--tertiary))', strokeDasharray: '3 2' }
const EDGE_DONE    = { stroke: 'hsl(var(--status-vfr))' }

// ── Custom nodes ──────────────────────────────────────────────────────────────

function AgentNode({ data }: NodeProps) {
  const colors = STATUS_COLORS[data.status ?? 'idle']
  return (
    <>
      <Handle type="target" position={Position.Top} />
      <div
        style={{
          padding: '10px 14px',
          borderRadius: 14,
          fontSize: 12,
          fontWeight: 600,
          minWidth: 120,
          textAlign: 'center',
          transition: 'all 220ms ease',
          backdropFilter: 'blur(8px)',
          border: `2px solid ${colors.border}`,
          boxShadow: '0 8px 18px rgba(0, 0, 0, 0.2)',
          backgroundColor: colors.bg,
          color: colors.text,
        }}
      >
        {data.status === 'running' && (
          <div style={{ marginBottom: 6, height: 2, width: '100%', overflow: 'hidden', borderRadius: 999, backgroundColor: `${colors.border}33` }}>
            <div style={{ height: '100%', width: '50%', borderRadius: 999, backgroundColor: colors.border, animation: 'shimmer 1s ease-in-out infinite' }} />
          </div>
        )}
        <p style={{ fontWeight: 700 }}>{data.label}</p>
        {data.details && (
          <p style={{ fontSize: 10, marginTop: 4, maxWidth: 140, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', opacity: 0.7 }}>{data.details}</p>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </>
  )
}

function ToolNode({ data }: NodeProps) {
  const colors = STATUS_COLORS[data.status ?? 'idle']
  return (
    <>
      <Handle type="target" position={Position.Top} />
      <div
        style={{
          padding: '8px 10px',
          borderRadius: 10,
          fontSize: 10,
          boxShadow: '0 6px 14px rgba(0, 0, 0, 0.2)',
          border: `2px solid ${colors.border}`,
          minWidth: 100,
          maxWidth: 160,
          textAlign: 'center',
          transition: 'all 220ms ease',
          backdropFilter: 'blur(4px)',
          backgroundColor: colors.bg,
          color: colors.text,
        }}
      >
        <p style={{ fontFamily: 'monospace', fontWeight: 700, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{data.label}</p>
        {data.input && (
          <p style={{ marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', opacity: 0.6 }}>{data.input}</p>
        )}
        {data.duration && (
          <p style={{ marginTop: 2, opacity: 0.6 }}>{data.duration}</p>
        )}
      </div>
    </>
  )
}

const nodeTypes = { agentNode: AgentNode, toolNode: ToolNode }

// ── Static graph topology ────────────────────────────────────────────────────

const SPECIALIST_X: Record<string, number> = {
  aviation_weather: 10,
  hk_weather:       155,
  aircraft:         300,
  general:          445,
  planning:         590,
}

const TOPOLOGY_NODES: Node[] = [
  { id: 'router', type: 'agentNode', position: { x: 215, y: 10 },
    data: { label: '🧭 Router', status: 'idle' } },
  { id: 'aviation_weather', type: 'agentNode', position: { x: SPECIALIST_X.aviation_weather, y: 160 },
    data: { label: '✈️ Aviation', status: 'idle' } },
  { id: 'hk_weather', type: 'agentNode', position: { x: SPECIALIST_X.hk_weather, y: 160 },
    data: { label: '🌦 HK Wx', status: 'idle' } },
  { id: 'aircraft', type: 'agentNode', position: { x: SPECIALIST_X.aircraft, y: 160 },
    data: { label: '🛩 Aircraft', status: 'idle' } },
  { id: 'general', type: 'agentNode', position: { x: SPECIALIST_X.general, y: 160 },
    data: { label: '🤖 General', status: 'idle' } },
  { id: 'planning', type: 'agentNode', position: { x: SPECIALIST_X.planning, y: 160 },
    data: { label: '🧠 Planning', status: 'idle' } },
]

const TOPOLOGY_EDGES: Edge[] = [
  { id: 'e-r-av', source: 'router', target: 'aviation_weather', style: EDGE_DEFAULT },
  { id: 'e-r-hk', source: 'router', target: 'hk_weather',       style: EDGE_DEFAULT },
  { id: 'e-r-ac', source: 'router', target: 'aircraft',         style: EDGE_DEFAULT },
  { id: 'e-r-gn', source: 'router', target: 'general',          style: EDGE_DEFAULT },
  { id: 'e-r-pl', source: 'router', target: 'planning',         style: EDGE_DEFAULT },
]

// ── Main Component ────────────────────────────────────────────────────────────

export default function UnifiedAgentView() {
  const theme = useTheme()
  const isSmallScreen = useMediaQuery(theme.breakpoints.down('md'))
  const { messages, isLoading, loadFromStorage, setLoading, addMessage, clearMessages } = useChatStore()
  const { addLog, clearLogs } = useWorkflowStore()

  const [streamingMsg, setStreamingMsg] = useState<Message | null>(null)
  const [showWorkflow, setShowWorkflow] = useState(false)
  const [voiceDraftText, setVoiceDraftText] = useState('')
  const [voiceDraftVersion, setVoiceDraftVersion] = useState(0)

  const sessionIdRef = useRef<string>(getOrCreateSessionId())
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const cancelStreamRef = useRef<(() => void) | null>(null)
  const cancelEventsRef = useRef<(() => void) | null>(null)

  const {
    isConnected: voiceConnected,
    isConnecting: voiceConnecting,
    isListening: voiceListening,
    autoSpeakEnabled,
    micPermission,
    interimTranscript,
    statusLabel: voiceStatusLabel,
    toggleConnection,
    startVoiceInput,
    stopVoiceInput,
    toggleAutoSpeak,
    speakText,
    stopSpeaking,
  } = useLiveKitVoice({
    onTranscriptFinal: (text) => {
      const spokenInput = text.trim()
      if (!spokenInput) return
      setVoiceDraftText(spokenInput)
      setVoiceDraftVersion((current) => current + 1)
    },
  })

  const [nodes, setNodes, onNodesChange] = useNodesState(TOPOLOGY_NODES)
  const [edges, setEdges, onEdgesChange] = useEdgesState(TOPOLOGY_EDGES)
  const activeToolIds = useRef<Map<string, string>>(new Map())
  const toolCountPerSpecialist = useRef<Record<string, number>>({})

  useEffect(() => {
    loadFromStorage(sessionIdRef.current)
  }, [loadFromStorage])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingMsg?.content])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        handleClear()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  useEffect(() => {
    return () => {
      cancelStreamRef.current?.()
      cancelEventsRef.current?.()
      stopSpeaking()
    }
  }, [stopSpeaking])

  const resetGraph = useCallback(() => {
    setNodes(TOPOLOGY_NODES.map(n => ({ ...n, data: { ...n.data, status: 'idle', details: '' } })))
    setEdges(TOPOLOGY_EDGES.map(e => ({ ...e, animated: false, style: EDGE_DEFAULT })))
    activeToolIds.current = new Map()
    toolCountPerSpecialist.current = {}
  }, [setNodes, setEdges])

  const setNodeStatus = useCallback(
    (id: string, status: string, details?: string) => {
      setNodes(prev =>
        prev.map(n => n.id === id ? { ...n, data: { ...n.data, status, details: details ?? n.data.details } } : n)
      )
    },
    [setNodes]
  )

  const handleClear = useCallback(() => {
    cancelStreamRef.current?.()
    cancelEventsRef.current?.()
    setStreamingMsg(null)
    clearMessages(sessionIdRef.current)
    clearLogs()
    resetGraph()
  }, [clearMessages, clearLogs, resetGraph])

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isLoading) return

    addMessage({ role: 'user', content: text, timestamp: new Date() }, sessionIdRef.current)
    setLoading(true)

    // Reset workflow visualization
    resetGraph()
    clearLogs()

    // Initialize streaming message
    const placeholder: Message = {
      role: 'agent',
      content: '',
      timestamp: new Date(),
      toolCalls: [],
      thinking: [],
    }
    setStreamingMsg(placeholder)

    let accumulated = ''
    let errored = false
    const collectedToolCalls: Message['toolCalls'] = []
    const collectedThinking: Message['thinking'] = []
    let collectedPlan: string[] | undefined
    let collectedRoute: string | undefined

    // Start workflow events stream first
    cancelEventsRef.current = streamAgent(
      `${API_BASE}/api/agent/events?session_id=${encodeURIComponent(sessionIdRef.current)}`,
      {
        onChunk: (rawData) => {
          try {
            const ev = JSON.parse(rawData)
            const { nodeId, event_type, status, details, route, parent_node, duration_ms, tool_input } = ev
            if (!nodeId) return

            // Routing decision
            if (event_type === 'routing_decision') {
              setNodeStatus('router', 'completed', `→ ${route}`)
              if (route) {
                setEdges(prev => prev.map(e => {
                  if (e.source !== 'router') return e
                  return e.target === route
                    ? { ...e, animated: true, style: EDGE_ACTIVE }
                    : { ...e, animated: false, style: EDGE_DEFAULT }
                }))
              }
              addLog(`[router] → ${route} (${duration_ms}ms)`)
              return
            }

            // Plan event
            if (event_type === 'plan') {
              const steps = Array.isArray(ev.steps) ? ev.steps : []
              setNodeStatus('planning', 'running', `Plan with ${steps.length} steps`)
              addLog(`[planning] plan created with ${steps.length} steps`)
              steps.forEach((step: string, idx: number) => {
                addLog(`  ${idx + 1}. ${step}`)
              })
              return
            }

            // Node lifecycle
            if (event_type === 'node') {
              const rfStatus = status === 'started' ? 'running' : status === 'completed' ? 'completed' : 'error'
              setNodeStatus(nodeId, rfStatus, details)

              if (status === 'started') {
                addLog(`[${nodeId}] started`)
              } else if (status === 'completed') {
                addLog(`[${nodeId}] completed (${duration_ms ?? 0}ms)`)
              } else if (status === 'failed') {
                addLog(`✗ [${nodeId}] failed: ${details}`)
              }
              return
            }

            // Tool call
            if (event_type === 'tool') {
              const parent = parent_node || 'general'
              if (status === 'started') {
                const count = toolCountPerSpecialist.current[parent] ?? 0
                const toolNodeId = `tool-${nodeId}-${Date.now()}`
                activeToolIds.current.set(nodeId, toolNodeId)
                toolCountPerSpecialist.current[parent] = count + 1

                const parentX = SPECIALIST_X[parent] ?? 200
                const inputSummary = tool_input
                  ? Object.entries(tool_input)
                      .slice(0, 3)
                      .map(([k, v]) => `${k}=${String(v).slice(0, 25)}`)
                      .join(', ')
                  : ''

                const newNode: Node = {
                  id: toolNodeId,
                  type: 'toolNode',
                  position: { x: parentX - 15, y: 310 + count * 90 },
                  data: { label: nodeId, status: 'running', input: inputSummary },
                }
                setNodes(prev => [...prev, newNode])
                setEdges(prev => [
                  ...prev,
                  {
                    id: `e-${parent}-${toolNodeId}`,
                    source: parent,
                    target: toolNodeId,
                    animated: true,
                    style: EDGE_TOOL,
                  },
                ])
                addLog(`  ⚙ ${nodeId}(${inputSummary || '…'})`)
              } else if (status === 'completed') {
                const toolNodeId = activeToolIds.current.get(nodeId)
                if (toolNodeId) {
                  setNodes(prev =>
                    prev.map(n =>
                      n.id === toolNodeId
                        ? { ...n, data: { ...n.data, status: 'completed', duration: `${duration_ms}ms` } }
                        : n
                    )
                  )
                  setEdges(prev =>
                    prev.map(e =>
                      e.target === toolNodeId ? { ...e, animated: false, style: EDGE_DONE } : e
                    )
                  )
                  activeToolIds.current.delete(nodeId)
                  addLog(`  ✓ ${nodeId} (${duration_ms}ms)`)
                }
              }
              return
            }

            // Error
            if (event_type === 'error') {
              addLog(`✗ Error: ${details}`)
              toast.error(`Error: ${String(details).slice(0, 80)}`)
            }
          } catch { /* keepalive or malformed */ }
        },
        onError: (err) => {
          addLog(`✗ Stream error: ${err.message}`)
        },
        onComplete: () => {},
      }
    )

    // Start chat stream
    const endpoint = `${API_BASE}/api/agent/stream?input=${encodeURIComponent(text)}&session_id=${encodeURIComponent(sessionIdRef.current)}`

    await new Promise<void>((resolve) => {
      cancelStreamRef.current = () => {
        errored = true
        resolve()
      }

      streamAgentFetch(endpoint, {
        onChunk: (chunk) => {
          accumulated += chunk
          setStreamingMsg(prev => prev ? { ...prev, content: accumulated } : placeholder)
        },
        onToolCall: (toolCall) => {
          let replaced = false
          for (let i = collectedToolCalls.length - 1; i >= 0; i--) {
            if (collectedToolCalls[i].name === toolCall.name && collectedToolCalls[i].status === 'running') {
              collectedToolCalls[i] = toolCall
              replaced = true
              break
            }
          }
          if (!replaced) collectedToolCalls.push(toolCall)
          setStreamingMsg(prev => prev ? { ...prev, toolCalls: [...collectedToolCalls] } : placeholder)
        },
        onThinking: (thinking) => {
          collectedThinking.push(thinking)
          setStreamingMsg(prev => prev ? { ...prev, thinking: [...collectedThinking] } : placeholder)
        },
        onPlan: (plan) => {
          collectedPlan = plan
          setStreamingMsg(prev => prev ? { ...prev, plan } : placeholder)
        },
        onRoute: (route) => {
          collectedRoute = route
          setStreamingMsg(prev => prev ? { ...prev, route } : placeholder)
        },
        onError: async () => {
          errored = true
          setStreamingMsg(null)
          toast.error('Stream error occurred')
          resolve()
        },
        onComplete: () => resolve(),
      })
    })

    cancelEventsRef.current?.()

    if (!errored && accumulated.trim()) {
      const finalMsg: Message = {
        ...placeholder,
        content: accumulated,
        toolCalls: collectedToolCalls,
        thinking: collectedThinking,
        plan: collectedPlan,
        route: collectedRoute,
      }
      addMessage(finalMsg, sessionIdRef.current)
      speakText(finalMsg.content)
      toast.success('Response complete')
    }

    setStreamingMsg(null)
    setLoading(false)
  }, [isLoading, addMessage, setLoading, resetGraph, clearLogs, setNodeStatus, setNodes, setEdges, addLog, speakText])

  const handleToggleVoiceConnection = useCallback(() => {
    void (async () => {
      const wasConnected = voiceConnected
      try {
        await toggleConnection()
        toast.success(wasConnected ? 'Voice session disconnected' : 'Voice session connected')
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Unable to toggle voice session'
        toast.error(message)
      }
    })()
  }, [toggleConnection, voiceConnected])

  const handleStartVoiceHold = useCallback(() => {
    void (async () => {
      try {
        await startVoiceInput()
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Unable to start microphone input'
        toast.error(message)
      }
    })()
  }, [startVoiceInput])

  const handleStopVoiceHold = useCallback(() => {
    stopVoiceInput()
  }, [stopVoiceInput])

  const isIdle = !isLoading && !streamingMsg
  const showWorkflowPanel = showWorkflow && messages.length > 0

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', p: { xs: 1.25, sm: 2, md: 3 }, gap: 1.25 }}>
      {messages.length > 0 && (
        <Stack direction="row" justifyContent="flex-end" spacing={1} flexWrap="wrap" useFlexGap>
          <Button
            variant={showWorkflow ? 'contained' : 'outlined'}
            color={showWorkflow ? 'secondary' : 'primary'}
            onClick={() => setShowWorkflow(!showWorkflow)}
            startIcon={<MaterialIcon icon={showWorkflow ? 'visibility_off' : 'account_tree'} />}
          >
            {showWorkflow ? (isSmallScreen ? 'Show Chat' : 'Hide Workflow') : 'Show Workflow'}
          </Button>

          <Button
            variant="outlined"
            color="error"
            onClick={handleClear}
            disabled={!isIdle}
            startIcon={<MaterialIcon icon="delete" />}
          >
            Clear
          </Button>
        </Stack>
      )}

      <Stack
        direction={showWorkflowPanel ? { xs: 'column', md: 'row' } : 'column'}
        spacing={1.5}
        sx={{ flex: 1, minHeight: 0 }}
      >
        <Paper
          variant="outlined"
          sx={{
            display: isSmallScreen && showWorkflowPanel ? 'none' : 'flex',
            flex: showWorkflowPanel ? { xs: 1, md: 0.55 } : 1,
            minHeight: 0,
            flexDirection: 'column',
            overflow: 'hidden',
            bgcolor: alpha(theme.palette.background.paper, 0.75),
            backdropFilter: 'blur(10px)',
          }}
        >
          <Box
            sx={{
              flex: 1,
              minHeight: 0,
              overflowY: 'auto',
              p: { xs: 1.25, sm: 2, md: 3 },
            }}
          >
            {messages.length === 0 && !streamingMsg ? (
              <Stack alignItems="center" justifyContent="center" spacing={2} sx={{ minHeight: '100%', textAlign: 'center', py: 3 }}>
                <Box
                  sx={{
                    width: 88,
                    height: 88,
                    borderRadius: 5,
                    display: 'grid',
                    placeItems: 'center',
                    color: 'secondary.main',
                    bgcolor: alpha(theme.palette.secondary.main, 0.12),
                  }}
                >
                  <MaterialIcon icon="cyclone" filled />
                </Box>

                <Typography variant="h4" fontWeight={800}>
                  Clear Skies Await
                </Typography>
                <Typography variant="body1" color="text.secondary" sx={{ maxWidth: 680 }}>
                  Real-time aviation weather intelligence with clearer workflows, better spacing, and Material UI structure.
                </Typography>

                <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.2} useFlexGap flexWrap="wrap" sx={{ width: '100%', maxWidth: 860 }}>
                  {QUICK_PROMPTS.map(({ text, icon }) => (
                    <Button
                      key={text}
                      onClick={() => sendMessage(text)}
                      disabled={!isIdle}
                      variant="outlined"
                      color="secondary"
                      startIcon={<MaterialIcon icon={icon} />}
                      sx={{ flex: 1, justifyContent: 'flex-start', minWidth: { xs: '100%', md: 260 }, py: 1.2 }}
                    >
                      {text}
                    </Button>
                  ))}
                </Stack>
              </Stack>
            ) : (
              <Stack spacing={2.2}>
                {messages.length > 0 && (
                  <Stack direction="row" justifyContent="center">
                    <Chip
                      size="small"
                      variant="outlined"
                      label={`Today • ${new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC', timeZoneName: 'short' })}`}
                    />
                  </Stack>
                )}

                {messages.map((msg, idx) => (
                  <MessageBubble key={idx} message={msg} />
                ))}

                {streamingMsg && <MessageBubble message={streamingMsg} isStreaming />}

                {isLoading && !streamingMsg && (
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ pl: 1 }}>
                    <CircularProgress size={16} />
                    <Typography variant="caption" color="text.secondary">
                      Processing...
                    </Typography>
                  </Stack>
                )}
              </Stack>
            )}
            <div ref={messagesEndRef} />
          </Box>

          <Box sx={{ p: { xs: 1.5, sm: 2 }, borderTop: `1px solid ${theme.palette.divider}` }}>
            <ChatInput
              onSend={sendMessage}
              disabled={!isIdle}
              placeholder="Ask about aviation weather conditions..."
              onToggleVoiceConnection={handleToggleVoiceConnection}
              onStartVoiceHold={handleStartVoiceHold}
              onStopVoiceHold={handleStopVoiceHold}
              onToggleAutoSpeak={toggleAutoSpeak}
              voiceConnected={voiceConnected}
              voiceConnecting={voiceConnecting}
              voiceListening={voiceListening}
              autoSpeakEnabled={autoSpeakEnabled}
              voiceStatusLabel={voiceStatusLabel}
              voiceInterimTranscript={interimTranscript}
              micPermission={micPermission}
              voiceDraftText={voiceDraftText}
              voiceDraftVersion={voiceDraftVersion}
            />
          </Box>
        </Paper>

        {showWorkflowPanel && (
          <Paper
            variant="outlined"
            sx={{
              flex: { xs: 1, md: 0.45 },
              minHeight: 0,
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              bgcolor: alpha(theme.palette.background.paper, 0.75),
              backdropFilter: 'blur(10px)',
            }}
          >
            <Stack direction="row" spacing={1} alignItems="center" sx={{ px: 2, py: 1.4, borderBottom: `1px solid ${theme.palette.divider}` }}>
              <MaterialIcon icon="account_tree" />
              <Typography variant="subtitle2" fontWeight={700}>
                Workflow Execution
              </Typography>
            </Stack>

            <Box sx={{ flex: 1, minHeight: 0 }}>
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                nodeTypes={nodeTypes}
                fitView
                fitViewOptions={{ padding: 0.25 }}
                minZoom={0.3}
              >
                <Background />
                <Controls />
                <MiniMap
                  nodeColor={(n) => STATUS_COLORS[n.data?.status ?? 'idle'].border}
                  maskColor={alpha(theme.palette.background.default, 0.45)}
                />
              </ReactFlow>
            </Box>
          </Paper>
        )}
      </Stack>
    </Box>
  )
}
