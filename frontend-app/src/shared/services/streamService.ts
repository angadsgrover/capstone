import { ToolCall, ThinkingStep } from '../types/agent'
import { StreamPayload } from '../types/api'

export interface StreamMetadata {
  toolCalls?: ToolCall[]
  thinking?: ThinkingStep[]
  plan?: string[]
  route?: string
}

export interface StreamOptions {
  /** Called with the raw `event.data` string for each SSE message event */
  onChunk?: (rawData: string) => void
  /** Called when a complete tool call event is received */
  onToolCall?: (toolCall: ToolCall) => void
  /** Called when a thinking/reasoning event is received */
  onThinking?: (thinking: ThinkingStep) => void
  /** Called when a plan is created */
  onPlan?: (plan: string[]) => void
  /** Called when routing decision is made */
  onRoute?: (route: string) => void
  /** Called when metadata is updated */
  onMetadata?: (metadata: StreamMetadata) => void
  onError?: (error: Error) => void
  onComplete?: () => void
}

/**
 * Subscribe to a server-sent event stream via EventSource.
 * `onChunk` receives the raw `event.data` string — callers decode as needed.
 * Returns a cleanup function to cancel the subscription.
 */
export function streamAgent(endpoint: string, options: StreamOptions = {}): () => void {
  const { onChunk, onError, onComplete } = options
  let cancelled = false

  const es = new EventSource(endpoint)

  es.addEventListener('message', (event) => {
    if (!cancelled) onChunk?.(event.data)
  })

  es.addEventListener('end', () => {
    if (!cancelled) onComplete?.()
    es.close()
  })

  es.addEventListener('error', () => {
    if (!cancelled) onError?.(new Error('SSE connection error'))
    es.close()
  })

  return () => {
    cancelled = true
    es.close()
  }
}

/**
 * Stream chat tokens via fetch (used by ChatView).
 * Parses `data: {"chunk":"..."}` SSE lines and passes each token to `onChunk`.
 * Also handles tool, thinking, plan, and route events with full metadata.
 * Returns an AbortController that can be used to cancel the request.
 */
export async function streamAgentFetch(
  endpoint: string,
  options: StreamOptions = {},
  abortController?: AbortController
): Promise<void> {
  const { onChunk, onToolCall, onThinking, onPlan, onRoute, onMetadata, onError, onComplete } = options
  const controller = abortController ?? new AbortController()

  const metadata: StreamMetadata = {
    toolCalls: [],
    thinking: [],
    plan: undefined,
    route: undefined,
  }

  try {
    const response = await fetch(endpoint, { signal: controller.signal })
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`)

    const reader = response.body?.getReader()
    if (!reader) throw new Error('Response body is not readable')

    const decoder = new TextDecoder()
    let buffer = ''
    let currentEvent = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) { onComplete?.(); break }

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')

      for (let i = 0; i < lines.length - 1; i++) {
        const line = lines[i].trim()

        // Capture event type
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim()
          if (currentEvent === 'end') {
            onMetadata?.(metadata)
            onComplete?.()
            reader.cancel()
            return
          }
          continue
        }

        // Parse data payload
        if (line.startsWith('data: ')) {
          try {
            const payload = JSON.parse(line.slice(6))
            if (!payload || typeof payload !== 'object') {
              currentEvent = ''
              continue
            }
            const typedPayload = payload as StreamPayload

            // Handle different event types
            if (currentEvent === 'chunk' || typedPayload.chunk) {
              onChunk?.(typedPayload.chunk || typedPayload.data || '')
            } else if (currentEvent === 'tool_start' || typedPayload.tool_start) {
              const toolCall: ToolCall = {
                name: typedPayload.tool_start || typedPayload.name || 'unknown_tool',
                input: typedPayload.tool_input || typedPayload.input || {},
                status: 'running',
                startTime: new Date(),
              }
              metadata.toolCalls!.push(toolCall)
              onToolCall?.(toolCall)
              onMetadata?.(metadata)
            } else if (currentEvent === 'tool_end' || typedPayload.tool_end) {
              const toolName = typedPayload.tool_end || typedPayload.name
              // Find the last running tool with this name (ES2023 findLast polyfill)
              const toolCalls = metadata.toolCalls || []
              let lastTool: ToolCall | undefined
              for (let i = toolCalls.length - 1; i >= 0; i--) {
                if (toolCalls[i].name === toolName && toolCalls[i].status === 'running') {
                  lastTool = toolCalls[i]
                  break
                }
              }
              if (lastTool) {
                lastTool.status = typedPayload.error ? 'error' : 'success'
                lastTool.output = typedPayload.output || typedPayload.result
                lastTool.error = typedPayload.error
                lastTool.endTime = new Date()
                lastTool.duration = typedPayload.duration || (lastTool.startTime ? Date.now() - new Date(lastTool.startTime).getTime() : undefined)
                onToolCall?.(lastTool)
                onMetadata?.(metadata)
              }
            } else if (currentEvent === 'thinking' || typedPayload.thinking) {
              const thinking: ThinkingStep = {
                type: typedPayload.type || 'reasoning',
                step: typedPayload.thinking || typedPayload.step || typedPayload.data || '',
                result: typedPayload.result,
                timestamp: new Date(),
              }
              metadata.thinking!.push(thinking)
              onThinking?.(thinking)
              onMetadata?.(metadata)
            } else if (currentEvent === 'plan' || typedPayload.plan) {
              metadata.plan = typedPayload.plan || typedPayload.steps
              const planThinking: ThinkingStep = {
                type: 'plan',
                step: `Generated ${(metadata.plan || []).length} execution step(s)`,
                timestamp: new Date(),
              }
              metadata.thinking!.push(planThinking)
              onThinking?.(planThinking)
              onPlan?.(metadata.plan!)
              onMetadata?.(metadata)
            } else if (currentEvent === 'route' || typedPayload.route) {
              metadata.route = typedPayload.route || typedPayload.specialist
              onRoute?.(metadata.route!)
              onMetadata?.(metadata)
            }

            currentEvent = ''  // Reset after processing
          } catch { /* ignore malformed lines */ }
        }
      }

      buffer = lines[lines.length - 1]
    }
  } catch (error) {
    // Don't treat abort as error - it's intentional cancellation
    if (error instanceof DOMException && error.name === 'AbortError') {
      return
    }
    onError?.(error instanceof Error ? error : new Error(String(error)))
  }
}
