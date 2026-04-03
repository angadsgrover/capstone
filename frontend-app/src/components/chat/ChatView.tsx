import { useState, useRef, useEffect, useCallback } from 'react'
import { toast } from 'sonner'
import { useChatStore } from '@/shared/state/chatStore'
import { agentService } from '@/shared/services/agentService'
import { streamAgentFetch } from '@/shared/services/streamService'
import { Message } from '@/shared/types/agent'
import { ExecutionTraceStepData } from '@/shared/types/api'
import MessageBubble from './MessageBubble'
import ChatInput from './ChatInput'
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

function isExecutionTraceStepData(value: unknown): value is ExecutionTraceStepData {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<ExecutionTraceStepData>
  return typeof candidate.step === 'number' && typeof candidate.task === 'string'
}

export default function ChatView() {
  const { messages, isLoading, loadFromStorage, setLoading, addMessage, clearMessages } =
    useChatStore()

  const [streamingMsg, setStreamingMsg] = useState<Message | null>(null)
  const sessionIdRef = useRef<string>(getOrCreateSessionId())
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

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
    return () => abortControllerRef.current?.abort()
  }, [])

  const handleAbort = useCallback(() => {
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    setStreamingMsg(null)
    setLoading(false)
    toast.info('Request cancelled')
  }, [setLoading])

  const handleClear = useCallback(() => {
    abortControllerRef.current?.abort()
    abortControllerRef.current = null
    setStreamingMsg(null)
    clearMessages(sessionIdRef.current)
  }, [clearMessages])

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isLoading) return

    addMessage({ role: 'user', content: text, timestamp: new Date() }, sessionIdRef.current)
    setLoading(true)

    if (STREAMING_ENABLED) {
      await sendStreaming(text)
    } else {
      await sendFull(text)
    }
  }, [isLoading])

  const sendStreaming = async (text: string) => {
    const placeholder: Message = {
      role: 'agent',
      content: '',
      timestamp: new Date(),
      toolCalls: [],
      thinking: [],
    }
    setStreamingMsg(placeholder)

    // Create abort controller for this request
    const controller = new AbortController()
    abortControllerRef.current = controller

    let accumulated = ''
    let aborted = false
    let errored = false
    const collectedToolCalls: Message['toolCalls'] = []
    const collectedThinking: Message['thinking'] = []
    let collectedPlan: string[] | undefined
    let collectedRoute: string | undefined

    const endpoint = `${API_BASE}/api/agent/stream?input=${encodeURIComponent(text)}&session_id=${encodeURIComponent(sessionIdRef.current)}`

    try {
      await streamAgentFetch(endpoint, {
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
          // Check if it was aborted by user
          if (controller.signal.aborted) {
            aborted = true
            return
          }
          errored = true
          setStreamingMsg(null)
          toast.warning('Streaming failed, falling back to standard response')
          await sendFull(text, true)
        },
        onComplete: () => {},
      }, controller)
    } catch {
      // Aborted requests throw - this is expected
      if (controller.signal.aborted) {
        aborted = true
      }
    }

    // Clean up abort controller ref
    if (abortControllerRef.current === controller) {
      abortControllerRef.current = null
    }

    // Don't add message if aborted
    if (aborted) {
      return
    }

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
    } else if (!errored) {
      // Defensive fallback: if SSE ends without any visible token content,
      // perform a regular request so the user never sees a silent empty response.
      setStreamingMsg(null)
      toast.warning('No streamed content received, falling back to standard response')
      await sendFull(text, true)
      return
    }
    setStreamingMsg(null)
    setLoading(false)
  }

  const sendFull = async (text: string, silentLoading = false) => {
    if (!silentLoading) setLoading(true)
    try {
      const response = await agentService.sendMessage(text, sessionIdRef.current)
      const plan = response.data?.plan
      const route = response.data?.route
      const executionTrace = Array.isArray(response.data?.execution_trace)
        ? response.data.execution_trace.filter(isExecutionTraceStepData)
        : []

      const thinking = executionTrace.map((step) => ({
        type: 'reasoning' as const,
        step: `Step ${step.step}: ${step.task}`,
        result: typeof step.result === 'string' ? step.result.slice(0, 180) : String(step.result),
        timestamp: new Date(),
      }))

      addMessage({
        role: 'agent',
        content: response.response,
        timestamp: new Date(),
        route,
        plan: Array.isArray(plan) ? plan : undefined,
        thinking: thinking.length ? thinking : undefined,
      }, sessionIdRef.current)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      toast.error(`Agent error: ${msg}`)
      addMessage({ role: 'agent', content: `Error: ${msg}`, timestamp: new Date() }, sessionIdRef.current)
    } finally {
      setLoading(false)
    }
  }

  const isIdle = !isLoading && !streamingMsg

  return (
    <div className="flex flex-col h-full w-full relative">

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
              Real-time aviation weather intelligence - HKO, HKYAA, and PolyU.
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
            {/* Timestamp divider */}
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

            {/* Typing indicator */}
            {isLoading && !streamingMsg && (
              <div className="flex items-center gap-3 pl-14">
                <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-surface-container-highest border border-outline-variant/15 shadow-lg">
                  <div className="w-1.5 h-1.5 bg-secondary rounded-full animate-pulse shadow-glow-secondary"></div>
                  <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">Processing weather data...</span>
                </div>
              </div>
            )}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Floating clear button */}
      {messages.length > 0 && (
        <button
          onClick={handleClear}
          title="Clear chat (⌘K)"
          disabled={!isIdle}
          className={cn(
            "fixed top-24 right-8 z-20 flex items-center gap-2 px-4 py-2.5 rounded-xl transition-all",
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
      )}

      {/* Input Area - Fixed at bottom with max-width */}
      <div className="w-full px-6 md:px-12 pb-8 pt-4">
        <div className="max-w-5xl mx-auto">
          <ChatInput
            onSend={sendMessage}
            onAbort={handleAbort}
            disabled={!isIdle}
            isProcessing={isLoading || Boolean(streamingMsg)}
            placeholder="Ask about aviation weather conditions..."
          />
        </div>
      </div>
    </div>
  )
}
