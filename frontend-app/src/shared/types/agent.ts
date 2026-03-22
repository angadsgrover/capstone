// Core agent types

export interface ToolCall {
  name: string
  input: Record<string, unknown>
  output?: string
  error?: string
  duration?: number
  startTime?: Date
  endTime?: Date
  retries?: number
  status?: 'running' | 'success' | 'error'
}

export interface ThinkingStep {
  type: 'plan' | 'reasoning' | 'synthesis'
  step: string
  result?: string
  timestamp: Date
}

export interface ExecutionTraceStep {
  step: number
  task: string
  result: string | Record<string, unknown>
}

export interface Message {
  role: 'user' | 'agent'
  content: string
  timestamp: Date
  toolCalls?: ToolCall[]
  thinking?: ThinkingStep[]
  plan?: string[]
  route?: string  // Which specialist handled this (aviation_weather, hk_weather, etc.)
}

export interface AgentRequest {
  input: string
  context?: Record<string, unknown>
}

export interface AgentResponse {
  response: string
  status: 'success' | 'error'
  data?: {
    route?: string
    plan?: string[]
    execution_trace?: ExecutionTraceStep[]
    multi_step?: boolean
    [key: string]: unknown
  }
}

export interface StreamEvent {
  type: 'start' | 'chunk' | 'end' | 'error' | 'tool' | 'thinking' | 'plan' | 'route'
  data: string
  metadata?: ToolCall | ThinkingStep | { route: string } | { plan: string[] }
  timestamp: Date
}
