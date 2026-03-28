import { useState, useRef, useEffect, useCallback } from 'react'
import { toast } from 'sonner'
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
import { agentService } from '@/shared/services/agentService'
import { streamAgent, streamAgentFetch } from '@/shared/services/streamService'
import { Message } from '@/shared/types/agent'
import MessageBubble from './chat/MessageBubble'
import ChatInput from './chat/ChatInput'
import MaterialIcon from '@/components/ui/MaterialIcon'
import { cn } from '@/lib/utils'

const API_BASE = import.meta.env.VITE_AGENT_API_URL
  ?? (import.meta.env.DEV ? 'http://localhost:8000' : window.location.origin)
const STREAMING_ENABLED = import.meta.env.VITE_ENABLE_STREAMING !== 'false'
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

const SPECIALIST_NODES = new Set(['aviation_weather', 'hk_weather', 'aircraft', 'general', 'planning'])

// ── Custom nodes ──────────────────────────────────────────────────────────────

function AgentNode({ data }: NodeProps) {
  const colors = STATUS_COLORS[data.status ?? 'idle']
  return (
    <>
      <Handle type="target" position={Position.Top} />
      <div
        className={cn(
          "px-4 py-2.5 rounded-xl text-xs font-semibold min-w-[120px] text-center transition-all duration-300",
          "backdrop-blur-xl border-2 shadow-lg"
        )}
        style={{ borderColor: colors.border, backgroundColor: colors.bg, color: colors.text }}
      >
        {data.status === 'running' && (
          <div className="mb-1.5 h-0.5 w-full overflow-hidden rounded-full" style={{ backgroundColor: `${colors.border}33` }}>
            <div className="h-full w-1/2 rounded-full animate-[shimmer_1s_ease-in-out_infinite]" style={{ backgroundColor: colors.border }} />
          </div>
        )}
        <p className="font-bold">{data.label}</p>
        {data.details && (
          <p className="text-[10px] mt-1 max-w-[140px] truncate opacity-70">{data.details}</p>
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
        className={cn(
          "px-2.5 py-2 rounded-lg text-[10px] shadow-md border-2 min-w-[100px] max-w-[160px] text-center transition-all duration-300",
          "backdrop-blur-sm"
        )}
        style={{ borderColor: colors.border, backgroundColor: colors.bg, color: colors.text }}
      >
        <p className="font-mono font-bold truncate">{data.label}</p>
        {data.input && (
          <p className="mt-0.5 truncate opacity-60">{data.input}</p>
        )}
        {data.duration && (
          <p className="mt-0.5 opacity-60">{data.duration}</p>
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
  const { messages, isLoading, loadFromStorage, setLoading, addMessage, clearMessages } = useChatStore()
  const { addLog, clearLogs } = useWorkflowStore()

  const [streamingMsg, setStreamingMsg] = useState<Message | null>(null)
  const [showWorkflow, setShowWorkflow] = useState(true)
  const [showMiniMap, setShowMiniMap] = useState(false)

  const sessionIdRef = useRef<string>(getOrCreateSessionId())
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const cancelStreamRef = useRef<(() => void) | null>(null)
  const cancelEventsRef = useRef<(() => void) | null>(null)

  const [nodes, setNodes, onNodesChange] = useNodesState(TOPOLOGY_NODES)
  const [edges, setEdges, onEdgesChange] = useEdgesState(TOPOLOGY_EDGES)
  const activeToolIds = useRef<Map<string, string>>(new Map())
  const toolCountPerSpecialist = useRef<Record<string, number>>({})

  useEffect(() => {
    loadFromStorage()
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
    }
  }, [])

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
    clearMessages()
    clearLogs()
    resetGraph()
  }, [clearMessages, clearLogs, resetGraph])

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isLoading) return

    addMessage({ role: 'user', content: text, timestamp: new Date() })
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
      addMessage(finalMsg)
      toast.success('Response complete')
    }

    setStreamingMsg(null)
    setLoading(false)
  }, [isLoading, addMessage, setLoading, resetGraph, clearLogs, setNodeStatus, setNodes, setEdges, addLog])

  const isIdle = !isLoading && !streamingMsg

  return (
    <div className="flex flex-col h-full w-full relative">
      {/* Toggle workflow button */}
      {messages.length > 0 && (
        <div className="fixed top-24 right-8 z-20 flex gap-2">
          <button
            onClick={() => setShowWorkflow(!showWorkflow)}
            className={cn(
              "flex items-center gap-2 px-4 py-2.5 rounded-xl transition-all font-medium text-xs uppercase tracking-wider shadow-lg",
              "bg-surface-container-high/80 backdrop-blur-sm border border-outline-variant/20",
              showWorkflow
                ? "text-secondary border-secondary/50 bg-secondary/10"
                : "text-on-surface-variant hover:border-secondary/30 hover:bg-secondary/5"
            )}
          >
            <MaterialIcon icon={showWorkflow ? "visibility_off" : "account_tree"} className="text-base" />
            <span>{showWorkflow ? 'Hide' : 'Show'} Workflow</span>
          </button>

          <button
            onClick={handleClear}
            title="Clear all (⌘K)"
            disabled={!isIdle}
            className={cn(
              "flex items-center gap-2 px-4 py-2.5 rounded-xl transition-all",
              "bg-surface-container-high/80 backdrop-blur-sm border border-outline-variant/20",
              "text-on-surface-variant text-xs font-medium uppercase tracking-wider shadow-lg",
              isIdle
                ? "hover:border-error/50 hover:text-error hover:bg-error/5 hover:shadow-error/20 active:scale-95 cursor-pointer"
                : "opacity-50 cursor-not-allowed"
            )}
          >
            <MaterialIcon icon="delete" className="text-base" />
            <span>Clear</span>
            <kbd className="ml-1 px-1.5 py-0.5 rounded bg-surface-container-highest/50 text-[9px] border border-outline-variant/20">⌘K</kbd>
          </button>
        </div>
      )}

      <div className="flex-1 overflow-hidden flex">
        {/* Chat column */}
        <div className={cn(
          "flex flex-col transition-all duration-300",
          showWorkflow && messages.length > 0 ? "w-1/2 border-r border-outline-variant/20" : "w-full"
        )}>
          {/* Background decoration */}
          <div className="absolute top-1/4 right-20 w-96 h-96 bg-primary/5 rounded-full blur-[120px] -z-10 pointer-events-none" />
          <div className="absolute bottom-40 left-20 w-80 h-80 bg-secondary/5 rounded-full blur-[100px] -z-10 pointer-events-none" />

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-6 md:px-12 py-8 space-y-8">
            {messages.length === 0 && !streamingMsg ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-12 max-w-5xl mx-auto">
                {/* Hero */}
                <div className="relative mb-8 flex justify-center">
                  <div className="absolute inset-0 bg-secondary/20 blur-2xl rounded-full animate-pulse" />
                  <div className="relative w-24 h-24 bg-surface-container-high rounded-[2rem] flex items-center justify-center border border-outline-variant/20 glass-panel">
                    <MaterialIcon icon="cyclone" className="text-secondary text-5xl" filled />
                  </div>
                </div>

                <h1 className="text-5xl md:text-6xl font-black text-on-surface tracking-tighter leading-tight mb-4">
                  Clear Skies <span className="text-secondary italic">Await.</span>
                </h1>
                <p className="text-on-surface-variant text-lg max-w-xl mx-auto font-medium mb-8">
                  Real-time aviation weather intelligence with visual workflow execution.
                </p>

                {/* Quick prompts */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 w-full max-w-3xl">
                  {QUICK_PROMPTS.map(({ text, icon }) => (
                    <button
                      key={text}
                      onClick={() => sendMessage(text)}
                      disabled={!isIdle}
                      className={cn(
                        "glass-panel p-6 rounded-xl border border-outline-variant/10 text-left transition-all group",
                        isIdle
                          ? "hover:border-secondary/50 hover:shadow-lg hover:shadow-secondary/10 active:scale-[0.98] cursor-pointer"
                          : "opacity-50 cursor-not-allowed"
                      )}
                    >
                      <MaterialIcon icon={icon} className="text-secondary mb-4 block text-2xl group-hover:scale-110 transition-transform" />
                      <div className="text-on-surface font-semibold mb-1">{text}</div>
                      <div className="text-xs text-on-surface-variant">Get real-time aviation weather data</div>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="max-w-6xl mx-auto w-full space-y-8">
                {messages.length > 0 && (
                  <div className="flex justify-center py-4">
                    <span className="text-[10px] font-bold tracking-[0.2em] text-on-surface-variant uppercase px-4 py-1.5 rounded-full bg-surface-container-low border border-outline-variant/10">
                      Today • {new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC', timeZoneName: 'short' })}
                    </span>
                  </div>
                )}

                {messages.map((msg, idx) => (
                  <MessageBubble key={idx} message={msg} />
                ))}

                {streamingMsg && (
                  <MessageBubble message={streamingMsg} isStreaming />
                )}

                {isLoading && !streamingMsg && (
                  <div className="flex items-center gap-3 pl-14">
                    <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-surface-container-highest border border-outline-variant/15 shadow-lg">
                      <div className="w-1.5 h-1.5 bg-secondary rounded-full animate-pulse shadow-glow-secondary"></div>
                      <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">Processing...</span>
                    </div>
                  </div>
                )}
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Area */}
          <div className="w-full px-6 md:px-12 pb-8 pt-4">
            <div className="max-w-5xl mx-auto">
              <ChatInput
                onSend={sendMessage}
                disabled={!isIdle}
                placeholder="Ask about aviation weather conditions..."
              />
            </div>
          </div>
        </div>

        {/* Workflow column */}
        {showWorkflow && messages.length > 0 && (
          <div className="w-1/2 flex flex-col bg-surface-container-lowest/30">
            <div className="flex items-center justify-between px-6 py-4 border-b border-outline-variant/20">
              <div className="flex items-center gap-2">
                <MaterialIcon icon="account_tree" className="text-secondary" />
                <h2 className="text-sm font-bold text-primary">Workflow Execution</h2>
              </div>
              <button
                onClick={() => setShowMiniMap(!showMiniMap)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-medium uppercase tracking-wider transition-all",
                  showMiniMap
                    ? "bg-secondary/10 text-secondary border border-secondary/30"
                    : "text-on-surface-variant hover:bg-surface-container-high border border-outline-variant/20"
                )}
              >
                <MaterialIcon icon="map" className="text-xs" />
                <span>Minimap</span>
              </button>
            </div>

            <div className="flex-1 overflow-hidden">
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
                {showMiniMap && (
                  <MiniMap
                    nodeColor={(n) => STATUS_COLORS[n.data?.status ?? 'idle'].border}
                    maskColor="hsl(var(--background) / 0.35)"
                  />
                )}
              </ReactFlow>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
