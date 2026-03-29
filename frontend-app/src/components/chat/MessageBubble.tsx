import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import MaterialIcon from '@/components/ui/MaterialIcon'
import { Message } from '@/shared/types/agent'
import ToolCallsSection from './ToolCallsSection'
import ThinkingSection from './ThinkingSection'
import LLMThinkingOutputSection from './LLMThinkingOutputSection'
import { useState } from 'react'
import { cn } from '@/lib/utils'

interface MessageBubbleProps {
  message: Message
  isStreaming?: boolean
}

export default function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)

  const copyToClipboard = async () => {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className={cn(
      "group flex animate-in fade-in-up slide-in-from-bottom-2 duration-500",
      isUser ? "justify-end" : "justify-start"
    )}>
      <div className={cn(
        "max-w-[92%] sm:max-w-[88%] md:max-w-[75%] flex gap-3 sm:gap-4",
        isUser ? "flex-row-reverse" : "flex-row"
      )}>

        {/* Avatar */}
        <div
          className={cn(
            "flex-shrink-0 mt-1 w-10 h-10 rounded-xl flex items-center justify-center shadow-lg transition-all duration-200 group-hover:scale-110 group-hover:shadow-xl",
            isUser
              ? "user-gradient shadow-primary/20 group-hover:shadow-primary/30"
              : "bg-gradient-to-br from-surface-container-high to-surface-container-highest border border-secondary/20 shadow-secondary/10 group-hover:shadow-secondary/20"
          )}
        >
          {isUser ? (
            <MaterialIcon icon="person" className="text-on-primary-container" filled />
          ) : (
            <MaterialIcon icon="auto_awesome" className="text-secondary" filled />
          )}
        </div>

        {/* Content */}
        <div className="flex flex-col gap-2">
          {/* Sender label with time */}
          <div className={cn(
            "flex items-center gap-2 text-[10px] font-bold uppercase tracking-wider",
            isUser ? "flex-row-reverse text-on-surface-variant" : "text-on-surface-variant"
          )}>
            <span>{isUser ? 'You' : 'PolyU Weather AI'}</span>
            <span className="text-on-surface-variant/40">•</span>
            <span className="text-on-surface-variant/60">
              {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>

          {/* Bubble */}
          <div
            className={cn(
              "relative rounded-2xl px-5 py-4 transition-all duration-300 group/bubble",
              isUser
                ? "user-gradient text-on-primary-container rounded-tr-sm shadow-lg shadow-primary/15 hover:shadow-primary/25"
                : "ai-bubble-glass text-on-surface rounded-tl-sm hover:border-secondary/20 backdrop-blur-xl"
            )}
          >
            {isUser ? (
              <p className="text-sm leading-relaxed whitespace-pre-wrap font-medium">{message.content}</p>
            ) : (
              <div className="prose prose-sm prose-invert max-w-none">
                {/* Thinking and Tools sections (collapsed by default) - shown FIRST before final output */}
                {((message.thinking && message.thinking.length > 0) || (message.plan && message.plan.length > 0) || (message.toolCalls && message.toolCalls.length > 0)) && (
                  <div className="not-prose mb-4">
                    {/* Thinking section */}
                    <ThinkingSection
                      thinking={message.thinking}
                      plan={message.plan}
                      route={message.route}
                    />

                    {/* Raw LLM thinking output */}
                    {message.thinking && message.thinking.length > 0 && (
                      <LLMThinkingOutputSection thinking={message.thinking} />
                    )}

                    {/* Tool calls */}
                    {message.toolCalls && message.toolCalls.length > 0 && (
                      <ToolCallsSection toolCalls={message.toolCalls} />
                    )}

                    {/* Visual separator between thinking/tools and final output */}
                    <div className="mt-4 flex items-center gap-3">
                      <div className="flex-1 h-px bg-gradient-to-r from-transparent via-outline-variant/30 to-transparent" />
                      <span className="text-[10px] font-semibold text-on-surface-variant/60 uppercase tracking-wider flex items-center gap-1.5">
                        <MaterialIcon icon="check_circle" className="text-secondary text-sm" filled />
                        Final Output
                      </span>
                      <div className="flex-1 h-px bg-gradient-to-r from-transparent via-outline-variant/30 to-transparent" />
                    </div>
                  </div>
                )}

                {/* Main content / Final Output */}
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ ...props }) => (
                      <p className="mb-3 last:mb-0 text-sm leading-relaxed text-on-surface" {...props} />
                    ),
                    ul: ({ ...props }) => (
                      <ul className="mb-3 ml-5 list-disc [&>li]:mb-1.5 text-sm text-on-surface marker:text-on-surface-variant/50" {...props} />
                    ),
                    ol: ({ ...props }) => (
                      <ol className="mb-3 ml-5 list-decimal [&>li]:mb-1.5 text-sm text-on-surface marker:text-on-surface-variant/50" {...props} />
                    ),
                    li: ({ ...props }) => <li className="[&>p]:mb-0 leading-relaxed" {...props} />,
                    h1: ({ ...props }) => (
                      <h1 className="text-lg font-bold mb-3 mt-4 first:mt-0 text-on-surface" {...props} />
                    ),
                    h2: ({ ...props }) => (
                      <h2 className="text-base font-semibold mb-2 mt-4 first:mt-0 text-on-surface" {...props} />
                    ),
                    h3: ({ ...props }) => (
                      <h3 className="text-sm font-semibold mb-2 mt-3 text-on-surface" {...props} />
                    ),
                    blockquote: ({ ...props }) => (
                      <blockquote
                        className="border-l-2 border-secondary/50 pl-4 italic text-on-surface-variant my-3 bg-secondary/5 py-2 rounded-r-lg"
                        {...props}
                      />
                    ),
                    a: ({ ...props }) => (
                      <a
                        className="text-secondary hover:text-secondary/80 underline underline-offset-2 decoration-secondary/30 hover:decoration-secondary/60 transition-colors"
                        target="_blank"
                        rel="noopener noreferrer"
                        {...props}
                      />
                    ),
                    code: ({ className, children, ...props }: any) => {
                      const isBlock = /language-(\w+)/.test(className || '')
                      if (isBlock) {
                        const [, lang] = /language-(\w+)/.exec(className || '') || []
                        return (
                          <div className="relative group/code my-3">
                            <div className="flex items-center justify-between px-4 py-2 bg-surface-container-lowest/80 border-b border-outline-variant/10 rounded-t-xl">
                              <span className="text-[10px] uppercase font-mono font-bold tracking-wider text-on-surface-variant">{lang}</span>
                              <button
                                onClick={() => navigator.clipboard.writeText(String(children))}
                                className="p-1.5 rounded-lg bg-surface-container/50 border border-outline-variant/20 text-on-surface-variant hover:text-secondary hover:bg-surface-container transition-all duration-200 opacity-0 group-hover/code:opacity-100"
                              >
                                <MaterialIcon icon="content_copy" className="text-xs" />
                              </button>
                            </div>
                            <pre className="bg-surface-container-lowest/80 border border-outline-variant/10 border-t-0 text-on-surface p-4 rounded-b-xl overflow-x-auto text-[13px] font-mono leading-relaxed">
                              <code className={className}>{children}</code>
                            </pre>
                          </div>
                        )
                      }
                      return (
                        <code
                          className="bg-surface-container/50 border border-outline-variant/20 px-1.5 py-0.5 rounded-md text-[13px] font-mono text-secondary"
                          {...props}
                        >
                          {children}
                        </code>
                      )
                    },
                    pre: ({ ...props }) => <pre className="hidden" {...props} />,
                    strong: ({ ...props }) => <strong className="font-semibold text-on-surface" {...props} />,
                    table: ({ ...props }) => (
                      <div className="overflow-x-auto my-3 rounded-lg border border-outline-variant/10">
                        <table className="w-full text-[13px]" {...props} />
                      </div>
                    ),
                    th: ({ ...props }) => (
                      <th className="px-3 py-2 bg-surface-container-high text-left font-semibold text-on-surface border-b border-outline-variant/10" {...props} />
                    ),
                    td: ({ ...props }) => (
                      <td className="px-3 py-2 text-on-surface-variant border-b border-outline-variant/5" {...props} />
                    ),
                  }}
                >
                  {message.content}
                </ReactMarkdown>

                {/* Streaming cursor */}
                {isStreaming && (
                  <span className="inline-block w-0.5 h-4 bg-secondary ml-0.5 animate-pulse align-text-bottom rounded-full shadow-glow-secondary" />
                )}
              </div>
            )}

            {/* Copy button for AI messages */}
            {!isUser && !isStreaming && message.content && (
              <button
                onClick={copyToClipboard}
                className={cn(
                  "absolute -bottom-2 -right-2 p-2 rounded-xl transition-all duration-200 shadow-lg",
                  "bg-surface-container-high border border-outline-variant/20",
                  "text-on-surface-variant hover:text-secondary hover:bg-surface-container-highest hover:border-secondary/30",
                  "opacity-0 group-hover/bubble:opacity-100 hover:scale-110 active:scale-95"
                )}
                title="Copy message"
              >
                {copied ? (
                  <MaterialIcon icon="check" className="text-sm text-secondary" />
                ) : (
                  <MaterialIcon icon="content_copy" className="text-sm" />
                )}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
