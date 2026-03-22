import { useState, useRef, useEffect, useCallback } from 'react'
import { toast } from 'sonner'
import { useChatStore } from '@/shared/state/chatStore'
import { agentService } from '@/shared/services/agentService'
import { streamAgentFetch } from '@/shared/services/streamService'
import { Message } from '@/shared/types/agent'
import { ExecutionTraceStepData } from '@/shared/types/api'
import MessageBubble from './MessageBubble'
import ChatInput from './ChatInput'
import { Button } from '@/components/ui/button'
import { FaRobot, FaTrash } from 'react-icons/fa'

const API_BASE = import.meta.env.VITE_AGENT_API_URL ?? 'http://localhost:8000'
const STREAMING_ENABLED = import.meta.env.VITE_ENABLE_STREAMING !== 'false'

const QUICK_PROMPTS = [
  "What's the weather in Hong Kong right now?",
  "Show METAR for VHHH",
  "Are there any active weather warnings?",
  "Aviation weather for Heathrow airport",
]

function isExecutionTraceStepData(value: unknown): value is ExecutionTraceStepData {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<ExecutionTraceStepData>
  return typeof candidate.step === 'number' && typeof candidate.task === 'string'
}

export default function ChatView() {
  const { messages, isLoading, loadFromStorage, setLoading, addMessage, clearMessages } =
    useChatStore()

  // Tracks the message being streamed (partial content)
  const [streamingMsg, setStreamingMsg] = useState<Message | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const cancelStreamRef = useRef<(() => void) | null>(null)

  // Load history on mount
  useEffect(() => {
    loadFromStorage()
  }, [loadFromStorage])

  // Auto-scroll on new messages or stream updates
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingMsg?.content])

  // Cmd+K → clear chat
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

  // Cleanup active stream on unmount
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
          setStreamingMsg(prev => prev ? {
            ...prev,
            content: accumulated
          } : placeholder)
        },
        onToolCall: (toolCall) => {
          // Keep latest snapshot by replacing the most recent matching running entry.
          let replaced = false
          for (let i = collectedToolCalls.length - 1; i >= 0; i--) {
            if (collectedToolCalls[i].name === toolCall.name && collectedToolCalls[i].status === 'running') {
              collectedToolCalls[i] = toolCall
              replaced = true
              break
            }
          }
          if (!replaced) collectedToolCalls.push(toolCall)

          setStreamingMsg(prev => {
            if (!prev) return placeholder
            return { ...prev, toolCalls: [...collectedToolCalls] }
          })
        },
        onThinking: (thinking) => {
          collectedThinking.push(thinking)
          setStreamingMsg(prev => {
            if (!prev) return placeholder
            return {
              ...prev,
              thinking: [...collectedThinking],
            }
          })
        },
        onPlan: (plan) => {
          collectedPlan = plan
          setStreamingMsg(prev => {
            if (!prev) return placeholder
            return { ...prev, plan }
          })
        },
        onRoute: (route) => {
          collectedRoute = route
          setStreamingMsg(prev => {
            if (!prev) return placeholder
            return { ...prev, route }
          })
        },
        onError: async () => {
          // Stream failed — fall back to full response
          errored = true
          setStreamingMsg(null)
          toast.warning('Streaming failed, falling back to standard response')
          await sendFull(text, true)
          resolve()
        },
        onComplete: () => {
          resolve()
        },
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
    <div
      className="flex flex-col rounded-3xl border border-white/[0.08] bg-[hsl(228_22%_11%)]/90 backdrop-blur-2xl shadow-2xl shadow-black/20 overflow-hidden"
      style={{ height: 'calc(100vh - 160px)', minHeight: '420px' }}
    >
      {/* Chat header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.06] bg-white/[0.02]">
        <div className="flex items-center gap-3">
          <div className="relative w-10 h-10 rounded-2xl bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <FaRobot className="text-white" size={16} />
            <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-white/20 to-transparent" />
          </div>
          <div>
            <p className="text-sm font-semibold text-white/90">AI Assistant</p>
            <p className="text-xs text-white/40">
              {isLoading ? (
                <span className="inline-flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  Processing...
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  Online
                </span>
              )}
            </p>
          </div>
        </div>

        <Button
          variant="ghost"
          size="sm"
          onClick={handleClear}
          title="Clear chat (⌘K)"
          className="h-8 gap-1.5 text-xs rounded-xl text-white/40 hover:text-red-400 hover:bg-red-500/10 transition-all duration-200"
        >
          <FaTrash size={11} />
          Clear
        </Button>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">
        {messages.length === 0 && !streamingMsg ? (
          /* Empty state */
          <div className="flex flex-col items-center justify-center h-full text-center py-8">
            <div className="w-16 h-16 rounded-3xl bg-gradient-to-br from-indigo-500/20 via-purple-500/20 to-pink-500/20 flex items-center justify-center mb-5 border border-white/[0.08]">
              <FaRobot className="text-indigo-400" size={28} />
            </div>
            <h3 className="text-xl font-semibold text-white/90 mb-2">
              How can I help you today?
            </h3>
            <p className="text-sm text-white/40 max-w-sm mb-8">
              Ask me about aviation weather, METAR/TAF reports, flight conditions, and more.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-lg">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => sendMessage(prompt)}
                  className="group text-left text-sm px-4 py-3.5 rounded-2xl border border-white/[0.08] bg-white/[0.03]
                    hover:bg-white/[0.06] hover:border-white/[0.12] text-white/60 hover:text-white/80 transition-all duration-200"
                >
                  <span className="inline-block group-hover:translate-x-0.5 transition-transform duration-200">{prompt}</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((msg, idx) => (
              <MessageBubble key={idx} message={msg} />
            ))}

            {/* Streaming (in-progress) bubble */}
            {streamingMsg && (
              <MessageBubble message={streamingMsg} isStreaming />
            )}

            {/* Thinking dots (no content yet) */}
            {isLoading && !streamingMsg && (
              <div className="flex justify-start">
                <div className="flex gap-3 items-center">
                  <div className="w-9 h-9 rounded-2xl bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 flex items-center justify-center flex-shrink-0 shadow-lg shadow-indigo-500/20">
                    <FaRobot className="text-white" size={14} />
                  </div>
                  <div className="px-5 py-4 bg-white/[0.05] border border-white/[0.08] rounded-2xl rounded-tl-md">
                    <div className="flex gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-indigo-400/60 animate-bounce" />
                      <span className="w-2 h-2 rounded-full bg-purple-400/60 animate-bounce [animation-delay:0.15s]" />
                      <span className="w-2 h-2 rounded-full bg-pink-400/60 animate-bounce [animation-delay:0.3s]" />
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
        placeholder="Ask about weather... (Enter to send, Shift+Enter for newline)"
      />
    </div>
  )
}
