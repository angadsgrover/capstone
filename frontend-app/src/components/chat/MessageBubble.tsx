import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Bot, User, Copy, Check, Clock } from 'lucide-react'
import { Message } from '@/shared/types/agent'
import ToolCallsSection from './ToolCallsSection'
import ThinkingSection from './ThinkingSection'
import { useState } from 'react'

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
    <div className={`group flex ${isUser ? 'justify-end' : 'justify-start'} animate-in fade-in-0 slide-in-from-bottom-2 duration-300`}>
      <div className={`max-w-[85%] flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>

        {/* Avatar */}
        <div
          className={`flex-shrink-0 mt-0.5 w-8 h-8 rounded-xl flex items-center justify-center shadow-lg transition-transform duration-200 group-hover:scale-105
            ${isUser
              ? 'bg-gradient-to-br from-blue-500 to-cyan-500 shadow-blue-500/20'
              : 'bg-gradient-to-br from-indigo-500 via-violet-500 to-purple-600 shadow-indigo-500/20'
            }`}
        >
          {isUser ? (
            <User className="text-white h-4 w-4" />
          ) : (
            <Bot className="text-white h-4 w-4" />
          )}
        </div>

        {/* Content */}
        <div className="flex flex-col gap-1">
          {/* Sender label */}
          <span className={`text-[10px] font-medium tracking-wide uppercase ${isUser ? 'text-right text-white/30' : 'text-white/30'}`}>
            {isUser ? 'You' : 'Assistant'}
          </span>

          {/* Bubble */}
          <div
            className={`relative rounded-2xl px-4 py-3 transition-all duration-200
              ${isUser
                ? 'bg-gradient-to-br from-blue-500 to-blue-600 text-white rounded-tr-sm shadow-lg shadow-blue-500/15'
                : 'bg-white/[0.04] border border-white/[0.06] text-white/90 rounded-tl-sm hover:bg-white/[0.05] hover:border-white/[0.08]'
              }`}
          >
            {isUser ? (
              <p className="text-[14px] leading-relaxed whitespace-pre-wrap">{message.content}</p>
            ) : (
              <div className="prose prose-sm prose-invert max-w-none">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ ...props }) => (
                      <p className="mb-3 last:mb-0 text-[14px] leading-relaxed text-white/85" {...props} />
                    ),
                    ul: ({ ...props }) => (
                      <ul className="mb-3 ml-5 list-disc [&>li]:mb-1.5 text-[14px] text-white/85 marker:text-white/30" {...props} />
                    ),
                    ol: ({ ...props }) => (
                      <ol className="mb-3 ml-5 list-decimal [&>li]:mb-1.5 text-[14px] text-white/85 marker:text-white/30" {...props} />
                    ),
                    li: ({ ...props }) => <li className="[&>p]:mb-0 leading-relaxed" {...props} />,
                    h1: ({ ...props }) => (
                      <h1 className="text-lg font-bold mb-3 mt-4 first:mt-0 text-white" {...props} />
                    ),
                    h2: ({ ...props }) => (
                      <h2 className="text-base font-semibold mb-2 mt-4 first:mt-0 text-white" {...props} />
                    ),
                    h3: ({ ...props }) => (
                      <h3 className="text-sm font-semibold mb-2 mt-3 text-white" {...props} />
                    ),
                    blockquote: ({ ...props }) => (
                      <blockquote
                        className="border-l-2 border-indigo-500/50 pl-4 italic text-white/60 my-3 bg-indigo-500/5 py-2 rounded-r-lg"
                        {...props}
                      />
                    ),
                    a: ({ ...props }) => (
                      <a
                        className="text-indigo-400 hover:text-indigo-300 underline underline-offset-2 decoration-indigo-400/30 hover:decoration-indigo-400/60 transition-colors"
                        target="_blank"
                        rel="noopener noreferrer"
                        {...props}
                      />
                    ),
                    code: ({ className, children, ...props }: any) => {
                      const isBlock = /language-(\w+)/.test(className || '')
                      if (isBlock) {
                        return (
                          <div className="relative group/code my-3">
                            <pre className="bg-slate-950/80 border border-white/[0.06] text-white/90 p-4 rounded-xl overflow-x-auto text-[13px] font-mono leading-relaxed">
                              <code className={className}>{children}</code>
                            </pre>
                            <button
                              onClick={() => navigator.clipboard.writeText(String(children))}
                              className="absolute top-2 right-2 p-1.5 rounded-lg bg-white/5 border border-white/10 text-white/40 hover:text-white hover:bg-white/10 opacity-0 group-hover/code:opacity-100 transition-all duration-200"
                            >
                              <Copy className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        )
                      }
                      return (
                        <code
                          className="bg-white/[0.08] border border-white/[0.06] px-1.5 py-0.5 rounded-md text-[13px] font-mono text-indigo-300"
                          {...props}
                        >
                          {children}
                        </code>
                      )
                    },
                    pre: ({ ...props }) => <pre className="hidden" {...props} />,
                    strong: ({ ...props }) => <strong className="font-semibold text-white" {...props} />,
                    table: ({ ...props }) => (
                      <div className="overflow-x-auto my-3 rounded-lg border border-white/[0.06]">
                        <table className="w-full text-[13px]" {...props} />
                      </div>
                    ),
                    th: ({ ...props }) => (
                      <th className="px-3 py-2 bg-white/[0.04] text-left font-semibold text-white/80 border-b border-white/[0.06]" {...props} />
                    ),
                    td: ({ ...props }) => (
                      <td className="px-3 py-2 text-white/70 border-b border-white/[0.04]" {...props} />
                    ),
                  }}
                >
                  {message.content}
                </ReactMarkdown>

                {/* Streaming cursor */}
                {isStreaming && (
                  <span className="inline-block w-0.5 h-4 bg-indigo-400 ml-0.5 animate-pulse align-text-bottom rounded-full" />
                )}

                {/* Thinking section */}
                <ThinkingSection thinking={message.thinking} plan={message.plan} route={message.route} />

                {/* Tool calls */}
                {message.toolCalls && message.toolCalls.length > 0 && (
                  <ToolCallsSection toolCalls={message.toolCalls} />
                )}
              </div>
            )}

            {/* Copy button for AI messages */}
            {!isUser && !isStreaming && message.content && (
              <button
                onClick={copyToClipboard}
                className="absolute -bottom-1 -right-1 p-1.5 rounded-lg bg-slate-800 border border-white/10 text-white/40 hover:text-white hover:bg-slate-700 opacity-0 group-hover:opacity-100 transition-all duration-200 shadow-lg"
                title="Copy message"
              >
                {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
              </button>
            )}
          </div>

          {/* Timestamp */}
          <div
            className={`flex items-center gap-1.5 text-[10px] ${
              isUser ? 'justify-end text-white/30' : 'text-white/25'
            }`}
          >
            <Clock className="h-2.5 w-2.5" />
            {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </div>
        </div>
      </div>
    </div>
  )
}
