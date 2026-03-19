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
      <div className={`max-w-[90%] flex gap-2 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
        {/* Avatar */}
        <div
          className={`flex-shrink-0 mt-1 w-8 h-8 rounded-full flex items-center justify-center
            ${isUser ? 'bg-blue-500' : 'bg-indigo-500'}`}
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
              ? 'bg-blue-500 text-white rounded-tr-none'
              : 'bg-zinc-100 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-100 rounded-tl-none'
            }`}
        >
          {isUser ? (
            <p className="text-sm whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose prose-sm max-w-none dark:prose-invert">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  p: ({ ...props }) => <p className="mb-3 last:mb-0 text-sm" {...props} />,
                  ul: ({ ...props }) => <ul className="mb-3 ml-5 list-disc [&>li]:mb-1 text-sm" {...props} />,
                  ol: ({ ...props }) => <ol className="mb-3 ml-5 list-decimal [&>li]:mb-1 text-sm" {...props} />,
                  li: ({ ...props }) => <li className="[&>p]:mb-0" {...props} />,
                  h1: ({ ...props }) => <h1 className="text-lg font-bold mb-2 mt-3 first:mt-0" {...props} />,
                  h2: ({ ...props }) => <h2 className="text-base font-semibold mb-2 mt-3 first:mt-0" {...props} />,
                  h3: ({ ...props }) => <h3 className="text-sm font-medium mb-1 mt-2" {...props} />,
                  blockquote: ({ ...props }) => (
                    <blockquote
                      className="border-l-4 border-blue-400 pl-3 italic text-zinc-600 dark:text-zinc-300 my-2"
                      {...props}
                    />
                  ),
                  a: ({ ...props }) => (
                    <a
                      className="text-blue-500 hover:underline"
                      target="_blank"
                      rel="noopener noreferrer"
                      {...props}
                    />
                  ),
                  code: ({ className, children, ...props }: any) => {
                    const isBlock = /language-(\w+)/.test(className || '')
                    if (isBlock) {
                      return (
                        <pre className="bg-zinc-800 text-zinc-100 p-3 rounded-lg my-2 overflow-x-auto text-xs font-mono border border-zinc-700">
                          <code className={className}>{children}</code>
                        </pre>
                      )
                    }
                    return (
                      <code
                        className="bg-zinc-200 dark:bg-zinc-800 px-1.5 py-0.5 rounded text-xs font-mono"
                        {...props}
                      >
                        {children}
                      </code>
                    )
                  },
                  pre: ({ ...props }) => <pre className="hidden" {...props} />,
                  strong: ({ ...props }) => <strong className="font-semibold" {...props} />,
                }}
              >
                {message.content}
              </ReactMarkdown>
              {/* Blinking cursor while streaming */}
              {isStreaming && (
                <span className="inline-block w-0.5 h-4 bg-indigo-400 ml-0.5 animate-pulse align-text-bottom" />
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
            className={`text-xs mt-1.5 ${
              isUser ? 'text-blue-100 text-right' : 'text-zinc-400 dark:text-zinc-500'
            }`}
          >
            {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </div>
        </div>
      </div>
    </div>
  )
}
