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
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const API_BASE = import.meta.env.VITE_AGENT_API_URL ?? 'http://localhost:8000'

// ── Colours ───────────────────────────────────────────────────────────────────

const STATUS_BORDER: Record<string, string> = {
  idle:      '#94a3b8',
  running:   '#3b82f6',
  completed: '#22c55e',
  error:     '#ef4444',
}
const STATUS_BG: Record<string, string> = {
  idle:      '#f8fafc',
  running:   '#dbeafe',
  completed: '#dcfce7',
  error:     '#fee2e2',
}
const EDGE_DEFAULT = { stroke: '#cbd5e1', strokeDasharray: '5 3' }
const EDGE_ACTIVE  = { stroke: '#3b82f6', strokeWidth: 2 }
const EDGE_TOOL    = { stroke: '#f59e0b', strokeDasharray: '3 2' }
const EDGE_DONE    = { stroke: '#22c55e' }

const SPECIALIST_NODES = new Set(['aviation_weather', 'hk_weather', 'aircraft', 'general', 'planning'])

// ── Custom nodes ──────────────────────────────────────────────────────────────

function AgentNode({ data }: NodeProps) {
  const border = STATUS_BORDER[data.status ?? 'idle']
  const bg     = STATUS_BG[data.status ?? 'idle']
  return (
    <>
      <Handle type="target" position={Position.Top} />
      <div
        className="px-3 py-2 rounded-xl text-xs font-medium shadow-sm border-2 min-w-[110px] text-center transition-all"
        style={{ borderColor: border, backgroundColor: bg, color: '#1e293b' }}
      >
        {data.status === 'running' && (
          <div className="mb-1 h-0.5 w-full overflow-hidden rounded-full bg-blue-100">
            <div className="h-full w-1/2 rounded-full bg-blue-400 animate-[shimmer_1s_ease-in-out_infinite]" />
          </div>
        )}
        <p className="font-semibold">{data.label}</p>
        {data.details && (
          <p className="text-[10px] text-zinc-500 mt-0.5 max-w-[130px] truncate">{data.details}</p>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </>
  )
}

function ToolNode({ data }: NodeProps) {
  const border = STATUS_BORDER[data.status ?? 'idle']
  const bg     = STATUS_BG[data.status ?? 'idle']
  return (
    <>
      <Handle type="target" position={Position.Top} />
      <div
        className="px-2 py-1.5 rounded-lg text-[10px] shadow border-2 min-w-[100px] max-w-[160px] text-center transition-all"
        style={{ borderColor: border, backgroundColor: bg, color: '#475569' }}
      >
        <p className="font-mono font-semibold truncate">{data.label}</p>
        {data.input && (
          <p className="text-zinc-400 mt-0.5 truncate">{data.input}</p>
        )}
        {data.duration && (
          <p className="text-zinc-400 mt-0.5">{data.duration}</p>
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
    <div className="flex flex-col gap-4">
      {/* Controls */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Workflow Execution</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col sm:flex-row gap-2">
            <Input
              value={userInput}
              onChange={(e) => handleInputChange(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleExecute()}
              placeholder="Enter your query…"
              disabled={isExecuting}
              className="flex-1"
            />
            <Button onClick={handleExecute} disabled={isExecuting || !userInput.trim()} className="gap-2">
              {isExecuting
                ? <><span className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />Running…</>
                : 'Execute'}
            </Button>
            <Button variant="outline" onClick={resetGraph} disabled={isExecuting}>Reset</Button>
          </div>
        </CardContent>
      </Card>

      {/* Graph + Logs */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* ReactFlow canvas */}
        <div className="lg:col-span-3 overflow-hidden rounded-xl border bg-card" style={{ height: 520 }}>
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
              nodeColor={(n) => STATUS_BORDER[n.data?.status ?? 'idle']}
              maskColor="rgba(0,0,0,0.04)"
            />
          </ReactFlow>
        </div>

        {/* Execution logs */}
        <Card className="lg:col-span-2 flex flex-col overflow-hidden" style={{ maxHeight: 520 }}>
          <div className="flex items-center justify-between px-4 py-3 border-b flex-shrink-0">
            <p className="text-sm font-semibold">Execution Log</p>
            <Button
              variant="ghost"
              size="sm"
              onClick={clearLogs}
              className="h-6 text-xs text-muted-foreground hover:text-destructive"
            >
              Clear
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-0.5">
            {logs.length === 0
              ? <p className="text-xs text-muted-foreground text-center py-8">No logs yet.</p>
              : logs.map((log, idx) => (
                  <pre key={idx} className="text-xs text-muted-foreground whitespace-pre-wrap font-mono leading-5">{log}</pre>
                ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
