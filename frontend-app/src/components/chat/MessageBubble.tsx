import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { FaRobot, FaUser } from 'react-icons/fa'
import { Message } from '@/shared/types/agent'
import ToolCallsSection from './ToolCallsSection'
import ThinkingSection from './ThinkingSection'

interface MessageBubbleProps {
  message: Message
  isStreaming?: boolean
}

export default function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[90%] flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
        {/* Avatar */}
        <div
          className={`flex-shrink-0 mt-1 w-9 h-9 rounded-2xl flex items-center justify-center shadow-lg
            ${isUser
              ? 'bg-gradient-to-br from-blue-500 to-cyan-500 shadow-blue-500/20'
              : 'bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 shadow-indigo-500/20'
            }`}
        >
          {isUser ? (
            <FaUser className="text-white" size={13} />
          ) : (
            <FaRobot className="text-white" size={13} />
          )}
        </div>

        {/* Bubble */}
        <div
          className={`rounded-2xl px-4 py-3 max-w-[85%]
            ${isUser
              ? 'bg-gradient-to-br from-blue-500 to-cyan-600 text-white rounded-tr-md shadow-lg shadow-blue-500/20'
              : 'bg-white/[0.05] border border-white/[0.08] text-white/90 rounded-tl-md backdrop-blur-sm'
            }`}
        >
          {isUser ? (
            <p className="text-sm whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose prose-sm prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  p: ({ ...props }) => <p className="mb-3 last:mb-0 text-sm text-white/85" {...props} />,
                  ul: ({ ...props }) => <ul className="mb-3 ml-5 list-disc [&>li]:mb-1 text-sm text-white/85" {...props} />,
                  ol: ({ ...props }) => <ol className="mb-3 ml-5 list-decimal [&>li]:mb-1 text-sm text-white/85" {...props} />,
                  li: ({ ...props }) => <li className="[&>p]:mb-0" {...props} />,
                  h1: ({ ...props }) => <h1 className="text-lg font-bold mb-2 mt-3 first:mt-0 text-white" {...props} />,
                  h2: ({ ...props }) => <h2 className="text-base font-semibold mb-2 mt-3 first:mt-0 text-white" {...props} />,
                  h3: ({ ...props }) => <h3 className="text-sm font-medium mb-1 mt-2 text-white" {...props} />,
                  blockquote: ({ ...props }) => (
                    <blockquote
                      className="border-l-4 border-indigo-400/50 pl-3 italic text-white/60 my-2"
                      {...props}
                    />
                  ),
                  a: ({ ...props }) => (
                    <a
                      className="text-indigo-400 hover:text-indigo-300 hover:underline transition-colors"
                      target="_blank"
                      rel="noopener noreferrer"
                      {...props}
                    />
                  ),
                  code: ({ className, children, ...props }: any) => {
                    const isBlock = /language-(\w+)/.test(className || '')
                    if (isBlock) {
                      return (
                        <pre className="bg-black/40 border border-white/[0.08] text-white/90 p-4 rounded-xl my-2 overflow-x-auto text-xs font-mono">
                          <code className={className}>{children}</code>
                        </pre>
                      )
                    }
                    return (
                      <code
                        className="bg-white/10 border border-white/[0.08] px-1.5 py-0.5 rounded-md text-xs font-mono text-indigo-300"
                        {...props}
                      >
                        {children}
                      </code>
                    )
                  },
                  pre: ({ ...props }) => <pre className="hidden" {...props} />,
                  strong: ({ ...props }) => <strong className="font-semibold text-white" {...props} />,
                }}
              >
                {message.content}
              </ReactMarkdown>
              {/* Blinking cursor while streaming */}
              {isStreaming && (
                <span className="inline-block w-0.5 h-4 bg-indigo-400 ml-0.5 animate-pulse align-text-bottom rounded-full" />
              )}

              {/* Thinking/Planning section */}
              <ThinkingSection thinking={message.thinking} plan={message.plan} route={message.route} />

              {/* Tool calls section */}
              {message.toolCalls && message.toolCalls.length > 0 && (
                <ToolCallsSection toolCalls={message.toolCalls} />
              )}
            </div>
          )}

          {/* Timestamp */}
          <div
            className={`text-xs mt-2 ${
              isUser ? 'text-white/50 text-right' : 'text-white/30'
            }`}
          >
            {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </div>
        </div>
      </div>
    </div>
  )
}
