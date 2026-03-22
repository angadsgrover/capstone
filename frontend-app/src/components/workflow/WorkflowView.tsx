import { useCallback, useEffect, useRef, useState } from 'react'
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
import { useWorkflowStore } from '@/shared/state/workflowStore'
import { agentService } from '@/shared/services/agentService'
import { streamAgent } from '@/shared/services/streamService'
import MaterialIcon from '@/components/ui/MaterialIcon'
import { cn } from '@/lib/utils'

const API_BASE = import.meta.env.VITE_AGENT_API_URL ?? 'http://localhost:8000'

// ── MD3 Status Colors ─────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, { border: string; bg: string; text: string }> = {
  idle:      { border: 'hsl(var(--outline-variant))', bg: 'hsl(var(--surface-container-low))', text: 'hsl(var(--on-surface-variant))' },
  running:   { border: 'hsl(var(--secondary))', bg: 'hsl(var(--secondary-container) / 0.3)', text: 'hsl(var(--secondary))' },
  completed: { border: 'hsl(140 60% 55%)', bg: 'hsl(140 60% 55% / 0.15)', text: 'hsl(140 65% 45%)' },
  error:     { border: 'hsl(var(--error))', bg: 'hsl(var(--error-container) / 0.2)', text: 'hsl(var(--error))' },
}
const EDGE_DEFAULT = { stroke: 'rgba(148, 163, 184, 0.4)', strokeDasharray: '5 3' }
const EDGE_ACTIVE  = { stroke: 'hsl(var(--secondary))', strokeWidth: 2.5 }
const EDGE_TOOL    = { stroke: 'hsl(39 100% 55%)', strokeDasharray: '3 2' }
const EDGE_DONE    = { stroke: 'hsl(140 60% 55%)' }

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

// ── Static graph topology (mirrors actual LangGraph structure) ────────────────
//   Router at top, 4 specialists in a row below, tool nodes added dynamically

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

// ── Component ─────────────────────────────────────────────────────────────────

export default function WorkflowView() {
  const { isExecuting, inputs, logs, setInputs, setExecuting, addLog, clearLogs } = useWorkflowStore()
  const [userInput, setUserInputLocal] = useState(inputs['input'] ?? '')
  const [nodes, setNodes, onNodesChange] = useNodesState(TOPOLOGY_NODES)
  const [edges, setEdges, onEdgesChange] = useEdgesState(TOPOLOGY_EDGES)
  const cancelEventsRef = useRef<(() => void) | null>(null)

  // Track tool placement (tool_name → nodeId) and per-specialist tool count
  const activeToolIds = useRef<Map<string, string>>(new Map())
  const toolCountPerSpecialist = useRef<Record<string, number>>({})

  const handleInputChange = (v: string) => {
    setUserInputLocal(v)
    setInputs({ input: v })
  }

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

  useEffect(() => () => cancelEventsRef.current?.(), [])

  const handleExecute = useCallback(async () => {
    if (isExecuting || !userInput.trim()) return
    cancelEventsRef.current?.()
    resetGraph()
    clearLogs()
    setExecuting(true)
    addLog(`▶ Starting: "${userInput}"`)

    try {
      // Subscribe SSE first — backend waits up to 10 s for queue
      cancelEventsRef.current = streamAgent(
        `${API_BASE}/api/agent/events?session_id=default`,
        {
          onChunk: (rawData) => {
            try {
              const ev = JSON.parse(rawData)
              const { nodeId, event_type, status, details, route, parent_node, duration_ms, tool_input } = ev
              if (!nodeId) return

              // ── Routing decision — router classified the query ─────────────
              if (event_type === 'routing_decision') {
                setNodeStatus('router', 'completed', `→ ${route}`)
                if (route) {
                  // Highlight the chosen edge, grey-out others
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

              if (event_type === 'plan') {
                const steps = Array.isArray(ev.steps) ? ev.steps : []
                setNodeStatus('planning', 'running', `Plan with ${steps.length} steps`)
                addLog(`[planning] plan created with ${steps.length} steps`)
                steps.forEach((step: string, idx: number) => {
                  addLog(`  ${idx + 1}. ${step}`)
                })
                return
              }

              // ── Node lifecycle (specialist or router started/completed) ────
              if (event_type === 'node') {
                const rfStatus = status === 'started' ? 'running' : status === 'completed' ? 'completed' : 'error'
                setNodeStatus(nodeId, rfStatus, details)

                if (status === 'started') {
                  addLog(`[${nodeId}] started`)
                } else if (status === 'completed') {
                  addLog(`[${nodeId}] completed (${duration_ms ?? 0}ms)`)
                  if (SPECIALIST_NODES.has(nodeId)) {
                    setExecuting(false)
                    addLog('✓ Workflow complete')
                    toast.success('Workflow completed')
                  }
                } else if (status === 'failed') {
                  addLog(`✗ [${nodeId}] failed: ${details}`)
                  setExecuting(false)
                  toast.error(`Workflow error in ${nodeId}`)
                }
                return
              }

              // ── Tool call ─────────────────────────────────────────────────
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

              // ── Error ─────────────────────────────────────────────────────
              if (event_type === 'error') {
                addLog(`✗ Error: ${details}`)
                setExecuting(false)
                toast.error(`Error: ${String(details).slice(0, 80)}`)
              }
            } catch { /* keepalive or malformed, skip */ }
          },
          onError: (err) => {
            setExecuting(false)
            addLog(`✗ Stream error: ${err.message}`)
            toast.error(`Stream lost: ${err.message}`)
          },
          onComplete: () => { setExecuting(false) },
        }
      )

      await agentService.executeWorkflow({ input: userInput, session_id: 'default' })
      addLog('Execution request accepted')
      toast.info('Workflow started')
    } catch (err) {
      cancelEventsRef.current?.()
      setExecuting(false)
      const msg = err instanceof Error ? err.message : String(err)
      addLog(`✗ ${msg}`)
      toast.error(`Failed to start: ${msg}`)
    }
  }, [isExecuting, userInput, resetGraph, clearLogs, setExecuting, addLog, setNodeStatus, setNodes, setEdges])

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Controls */}
      <div className={cn(
        "glass-panel rounded-2xl p-6 border border-outline-variant/20",
        "bg-surface-container-low/80 shadow-xl"
      )}>
        <div className="mb-4">
          <h2 className="text-lg font-bold text-primary">Workflow Execution</h2>
          <p className="text-sm text-on-surface-variant mt-1">Execute and monitor multi-step agent workflows</p>
        </div>
        <div className="flex flex-col sm:flex-row gap-3">
          <input
            type="text"
            value={userInput}
            onChange={(e) => handleInputChange(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleExecute()}
            placeholder="Enter your query…"
            disabled={isExecuting}
            className={cn(
              "flex-1 px-4 py-3 rounded-xl bg-surface-container-highest/60 backdrop-blur-xl",
              "border border-outline-variant/20 text-on-surface placeholder:text-on-surface-variant/40",
              "focus:outline-none focus:border-secondary/50 focus:ring-2 focus:ring-secondary/20",
              "transition-all duration-300",
              "disabled:opacity-40 disabled:cursor-not-allowed"
            )}
          />
          <button
            onClick={handleExecute}
            disabled={isExecuting || !userInput.trim()}
            className={cn(
              "px-6 py-3 rounded-xl font-semibold text-sm uppercase tracking-wider transition-all duration-300",
              "flex items-center justify-center gap-2",
              !isExecuting && userInput.trim()
                ? "user-gradient text-on-primary-container shadow-lg shadow-primary/20 hover:shadow-primary/30 hover:scale-105 hover:brightness-110 active:scale-95"
                : "bg-surface-container text-on-surface-variant/30 cursor-not-allowed"
            )}
          >
            {isExecuting ? (
              <>
                <MaterialIcon icon="pending" className="text-base animate-spin" />
                <span className="hidden sm:inline">Running…</span>
              </>
            ) : (
              <>
                <MaterialIcon icon="play_arrow" className="text-base" filled />
                <span className="hidden sm:inline">Execute</span>
              </>
            )}
          </button>
          <button
            onClick={resetGraph}
            disabled={isExecuting}
            className={cn(
              "px-6 py-3 rounded-xl font-medium text-sm transition-all duration-300",
              "bg-surface-container-high text-on-surface border border-outline-variant/20",
              "hover:bg-surface-container-highest hover:scale-105 hover:border-outline-variant/40",
              "active:scale-95",
              "disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
            )}
          >
            <MaterialIcon icon="restart_alt" className="text-base" />
          </button>
        </div>
      </div>

      {/* Graph + Logs */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* ReactFlow canvas */}
        <div className={cn(
          "lg:col-span-3 overflow-hidden rounded-2xl border border-outline-variant/20",
          "bg-surface-container-low shadow-xl"
        )} style={{ height: 520 }}>
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
              maskColor="rgba(0,0,0,0.04)"
            />
          </ReactFlow>
        </div>

        {/* Execution logs */}
        <div className={cn(
          "lg:col-span-2 flex flex-col overflow-hidden rounded-2xl border border-outline-variant/20",
          "bg-surface-container-low shadow-xl"
        )} style={{ maxHeight: 520 }}>
          <div className="flex items-center justify-between px-5 py-4 border-b border-outline-variant/10 flex-shrink-0">
            <div className="flex items-center gap-2">
              <MaterialIcon icon="terminal" className="text-secondary" />
              <p className="text-sm font-bold text-primary">Execution Log</p>
            </div>
            <button
              onClick={clearLogs}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200",
                "text-on-surface-variant hover:text-error hover:bg-surface-container-high hover:scale-105",
                "active:scale-95"
              )}
            >
              Clear
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-1">
            {logs.length === 0
              ? <div className="flex flex-col items-center justify-center h-full gap-3">
                  <MaterialIcon icon="pending_actions" className="text-4xl text-on-surface-variant/30" />
                  <p className="text-xs text-on-surface-variant/60 text-center">No logs yet. Execute a workflow to see events.</p>
                </div>
              : logs.map((log, idx) => (
                  <pre key={idx} className="text-xs text-on-surface-variant/80 whitespace-pre-wrap font-mono leading-relaxed">
                    {log}
                  </pre>
                ))}
          </div>
        </div>
      </div>
    </div>
  )
}
