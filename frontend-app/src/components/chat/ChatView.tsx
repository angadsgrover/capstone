import { useState, useRef, useEffect, useCallback } from 'react'
import { toast } from 'sonner'
import { useChatStore } from '@/shared/state/chatStore'
import { agentService } from '@/shared/services/agentService'
import { streamAgentFetch } from '@/shared/services/streamService'
import { Message } from '@/shared/types/agent'
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
      const executionTrace = response.data?.execution_trace ?? []

      const thinking = executionTrace.map((step: any) => ({
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
      className="flex flex-col rounded-xl border bg-card shadow-sm overflow-hidden"
      style={{ height: 'calc(100vh - 160px)', minHeight: '420px' }}
    >
      {/* Chat header */}
      <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-primary flex items-center justify-center">
            <FaRobot className="text-primary-foreground" size={13} />
          </div>
          <div>
            <p className="text-sm font-semibold">AI Assistant</p>
            <p className="text-xs text-muted-foreground">
              {isLoading ? 'Thinking…' : 'Ready'}
            </p>
          </div>
        </div>

        <Button
          variant="ghost"
          size="sm"
          onClick={handleClear}
          title="Clear chat (⌘K)"
          className="h-7 gap-1 text-xs text-muted-foreground hover:text-destructive"
        >
          <FaTrash size={11} />
          Clear
        </Button>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && !streamingMsg ? (
          /* Empty state */
          <div className="flex flex-col items-center justify-center h-full text-center py-8">
            <div className="w-14 h-14 rounded-full bg-primary/10 flex items-center justify-center mb-4">
              <FaRobot className="text-primary" size={24} />
            </div>
            <h3 className="text-lg font-semibold text-zinc-800 dark:text-zinc-200 mb-1">
              How can I help you today?
            </h3>
            <p className="text-sm text-muted-foreground max-w-xs mb-6">
              Ask me about weather, aviation conditions, METAR/TAF reports, and more.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-md">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => sendMessage(prompt)}
                  className="text-left text-xs px-3 py-2.5 rounded-lg border border-border bg-muted/60
                    hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                >
                  {prompt}
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
                <div className="flex gap-2 items-center">
                  <div className="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center flex-shrink-0">
                    <FaRobot className="text-white" size={13} />
                  </div>
                  <div className="px-4 py-3 bg-zinc-100 dark:bg-zinc-700 rounded-2xl rounded-tl-none">
                    <div className="flex gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-zinc-400 animate-bounce" />
                      <span className="w-2 h-2 rounded-full bg-zinc-400 animate-bounce [animation-delay:0.1s]" />
                      <span className="w-2 h-2 rounded-full bg-zinc-400 animate-bounce [animation-delay:0.2s]" />
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
        placeholder="Ask about weather… (Enter to send, Shift+Enter for newline)"
      />
    </div>
  )
}
