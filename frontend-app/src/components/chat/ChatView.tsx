import { useState, useRef, useEffect, useCallback } from 'react'
import { toast } from 'sonner'
import { useChatStore } from '@/shared/state/chatStore'
import { agentService } from '@/shared/services/agentService'
import { streamAgentFetch } from '@/shared/services/streamService'
import { Message } from '@/shared/types/agent'
import { ExecutionTraceStepData } from '@/shared/types/api'
import MessageBubble from './MessageBubble'
import ChatInput from './ChatInput'
import {
  Bot, Sparkles, Cloud, Plane, Wind, Trash2,
  MessageSquare, Zap
} from 'lucide-react'
import { cn } from '@/lib/utils'

const API_BASE = import.meta.env.VITE_AGENT_API_URL ?? 'http://localhost:8000'
const STREAMING_ENABLED = import.meta.env.VITE_ENABLE_STREAMING !== 'false'

const QUICK_PROMPTS = [
  { text: "What's the weather in Hong Kong?", icon: Cloud },
  { text: "Show METAR for VHHH", icon: Plane },
  { text: "Any active weather warnings?", icon: Wind },
  { text: "Aviation weather for Heathrow", icon: Zap },
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
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const cancelStreamRef = useRef<(() => void) | null>(null)

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
    return () => cancelStreamRef.current?.()
  }, [])

  const handleClear = useCallback(() => {
    cancelStreamRef.current?.()
    setStreamingMsg(null)
    clearMessages()
  }, [clearMessages])

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || isLoading) return

    addMessage({ role: 'user', content: text, timestamp: new Date() })
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

    let accumulated = ''
    let errored = false
    const collectedToolCalls: Message['toolCalls'] = []
    const collectedThinking: Message['thinking'] = []
    let collectedPlan: string[] | undefined
    let collectedRoute: string | undefined

    const endpoint = `${API_BASE}/api/agent/stream?input=${encodeURIComponent(text)}`

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
          toast.warning('Streaming failed, falling back to standard response')
          await sendFull(text, true)
          resolve()
        },
        onComplete: () => resolve(),
      })
    })

    if (!errored && accumulated) {
      const finalMsg: Message = {
        ...placeholder,
        content: accumulated,
        toolCalls: collectedToolCalls,
        thinking: collectedThinking,
        plan: collectedPlan,
        route: collectedRoute,
      }
      addMessage(finalMsg)
    }
    setStreamingMsg(null)
    setLoading(false)
  }

  const sendFull = async (text: string, silentLoading = false) => {
    if (!silentLoading) setLoading(true)
    try {
      const response = await agentService.sendMessage(text)
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
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      toast.error(`Agent error: ${msg}`)
      addMessage({ role: 'agent', content: `Error: ${msg}`, timestamp: new Date() })
    } finally {
      setLoading(false)
    }
  }

  const isIdle = !isLoading && !streamingMsg

  return (
    <div className={cn(
      "flex flex-col h-full rounded-2xl border backdrop-blur-xl overflow-hidden shadow-xl",
      // Light mode
      "border-slate-200/80 bg-white/80 shadow-slate-200/50",
      // Dark mode
      "dark:border-white/[0.06] dark:bg-slate-900/40 dark:shadow-black/20"
    )}>

      {/* Header */}
      <div className={cn(
        "flex items-center justify-between px-5 py-3.5 border-b",
        "border-slate-200/80 bg-slate-50/50 dark:border-white/[0.06] dark:bg-white/[0.02]"
      )}>
        <div className="flex items-center gap-3">
          <div className="relative">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 via-violet-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/25">
              <Bot className="text-white h-4 w-4" />
            </div>
            <Sparkles className="absolute -top-0.5 -right-0.5 h-3 w-3 text-amber-400" />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-900 dark:text-white/90">AI Assistant</p>
            <p className="text-[11px] text-slate-500 dark:text-white/40">
              {isLoading ? (
                <span className="inline-flex items-center gap-1.5">
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-500 opacity-75 animate-ping" />
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
                  </span>
                  Thinking...
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  Ready to help
                </span>
              )}
            </p>
          </div>
        </div>

        <button
          onClick={handleClear}
          title="Clear chat (⌘K)"
          className={cn(
            "flex items-center gap-1.5 h-8 px-3 text-xs font-medium rounded-lg border border-transparent transition-all duration-200",
            "text-slate-400 hover:text-red-500 hover:bg-red-50 hover:border-red-200",
            "dark:text-white/40 dark:hover:text-red-400 dark:hover:bg-red-500/10 dark:hover:border-red-500/20"
          )}
        >
          <Trash2 className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Clear</span>
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-5 space-y-6">
        {messages.length === 0 && !streamingMsg ? (
          <div className="flex flex-col items-center justify-center h-full text-center py-12">
            {/* Hero illustration */}
            <div className="relative mb-8">
              <div className="absolute inset-0 blur-3xl bg-gradient-to-r from-indigo-500/20 via-purple-500/20 to-pink-500/20 rounded-full scale-150" />
              <div className={cn(
                "relative w-20 h-20 rounded-2xl border flex items-center justify-center shadow-2xl",
                "bg-gradient-to-br from-white to-slate-50 border-slate-200",
                "dark:bg-gradient-to-br dark:from-slate-800 dark:to-slate-900 dark:border-white/[0.08]"
              )}>
                <MessageSquare className="h-8 w-8 text-indigo-500" />
                <div className="absolute -bottom-1 -right-1 w-6 h-6 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg">
                  <Sparkles className="h-3 w-3 text-white" />
                </div>
              </div>
            </div>

            <h3 className="text-xl font-semibold text-slate-900 dark:text-white mb-2">
              How can I help you today?
            </h3>
            <p className="text-sm text-slate-500 dark:text-white/40 max-w-sm mb-10">
              Ask about aviation weather, METAR/TAF reports, flight conditions, and real-time aircraft tracking.
            </p>

            {/* Quick prompts */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-lg">
              {QUICK_PROMPTS.map(({ text, icon: Icon }) => (
                <button
                  key={text}
                  onClick={() => sendMessage(text)}
                  className={cn(
                    "group text-left text-sm px-4 py-3.5 rounded-xl border transition-all duration-300",
                    "border-slate-200 bg-white hover:bg-gradient-to-r hover:from-indigo-50 hover:to-purple-50 hover:border-indigo-200",
                    "dark:border-white/[0.06] dark:bg-white/[0.02] dark:hover:from-indigo-500/10 dark:hover:to-purple-500/10 dark:hover:border-indigo-500/20",
                    "text-slate-600 hover:text-slate-900 dark:text-white/60 dark:hover:text-white/90"
                  )}
                >
                  <div className="flex items-center gap-3">
                    <div className={cn(
                      "flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center transition-colors duration-300",
                      "bg-slate-100 group-hover:bg-indigo-100 dark:bg-white/[0.05] dark:group-hover:bg-indigo-500/20"
                    )}>
                      <Icon className="h-4 w-4 text-slate-400 group-hover:text-indigo-500 dark:text-white/40 dark:group-hover:text-indigo-400 transition-colors duration-300" />
                    </div>
                    <span className="flex-1 group-hover:translate-x-0.5 transition-transform duration-200">{text}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg, idx) => (
              <MessageBubble key={idx} message={msg} />
            ))}

            {streamingMsg && (
              <MessageBubble message={streamingMsg} isStreaming />
            )}

            {/* Typing indicator */}
            {isLoading && !streamingMsg && (
              <div className="flex justify-start">
                <div className="flex gap-3 items-start">
                  <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-indigo-500 via-violet-500 to-purple-600 flex items-center justify-center flex-shrink-0 shadow-lg shadow-indigo-500/20">
                    <Bot className="text-white h-4 w-4" />
                  </div>
                  <div className={cn(
                    "px-4 py-3 border rounded-2xl rounded-tl-md",
                    "bg-slate-50 border-slate-200 dark:bg-white/[0.04] dark:border-white/[0.06]"
                  )}>
                    <div className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-indigo-400/60 animate-bounce" />
                      <span className="w-2 h-2 rounded-full bg-violet-400/60 animate-bounce [animation-delay:0.15s]" />
                      <span className="w-2 h-2 rounded-full bg-purple-400/60 animate-bounce [animation-delay:0.3s]" />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <ChatInput
        onSend={sendMessage}
        disabled={!isIdle}
        placeholder="Ask about aviation weather... (Enter to send)"
      />
    </div>
  )
}
