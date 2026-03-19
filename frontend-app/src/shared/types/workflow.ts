// Workflow types
export interface WorkflowNode {
  id: string
  label: string
  status: 'idle' | 'running' | 'completed' | 'error'
  data?: Record<string, any>
  position: { x: number; y: number }
}

export interface WorkflowEdge {
  id: string
  source: string
  target: string
  label?: string
}

export interface WorkflowInput {
  [key: string]: string | number | boolean | any
}

export interface WorkflowResult {
  status: 'pending' | 'executing' | 'completed' | 'error'
  output?: string | Record<string, any>
  error?: string
  endTime?: Date
}

export interface WorkflowEvent {
  type: 'node_started' | 'node_completed' | 'node_error'
  nodeId: string
  data?: Record<string, any>
  timestamp: Date
}
