import { useState } from 'react'
import { FaChevronDown, FaChevronRight, FaTools, FaCheckCircle, FaExclamationCircle, FaSpinner, FaRedo } from 'react-icons/fa'
import { ToolCall } from '@/shared/types/agent'

interface ToolCallsSectionProps {
  toolCalls: ToolCall[]
}

export default function ToolCallsSection({ toolCalls }: ToolCallsSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!toolCalls || toolCalls.length === 0) return null

  const successCount = toolCalls.filter(t => t.status === 'success').length
  const errorCount = toolCalls.filter(t => t.status === 'error').length
  const runningCount = toolCalls.filter(t => t.status === 'running').length

  return (
    <div className="mt-3 border border-amber-200 dark:border-amber-800 rounded-lg overflow-hidden bg-amber-50/50 dark:bg-amber-950/20">
      {/* Header - Collapsible */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/20 transition-colors"
      >
        {isExpanded ? <FaChevronDown size={10} /> : <FaChevronRight size={10} />}
        <FaTools size={11} />
        <span>Tool Calls ({toolCalls.length})</span>

        {/* Status badges */}
        <div className="flex gap-1.5 ml-auto">
          {runningCount > 0 && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded text-[10px]">
              <FaSpinner className="animate-spin" size={8} />
              {runningCount}
            </span>
          )}
          {successCount > 0 && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 rounded text-[10px]">
              <FaCheckCircle size={8} />
              {successCount}
            </span>
          )}
          {errorCount > 0 && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 rounded text-[10px]">
              <FaExclamationCircle size={8} />
              {errorCount}
            </span>
          )}
        </div>
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-3 pb-3 space-y-2">
          {toolCalls.map((tool, idx) => (
            <ToolCallItem key={idx} tool={tool} />
          ))}
        </div>
      )}
    </div>
  )
}

function ToolCallItem({ tool }: { tool: ToolCall }) {
  const [showDetails, setShowDetails] = useState(false)

  const statusIcon = () => {
    switch (tool.status) {
      case 'running':
        return <FaSpinner className="animate-spin text-blue-500" size={10} />
      case 'success':
        return <FaCheckCircle className="text-green-500" size={10} />
      case 'error':
        return <FaExclamationCircle className="text-red-500" size={10} />
      default:
        return null
    }
  }

  const statusColor = () => {
    switch (tool.status) {
      case 'running':
        return 'border-blue-300 dark:border-blue-700 bg-blue-50/50 dark:bg-blue-950/20'
      case 'success':
        return 'border-green-300 dark:border-green-700 bg-green-50/50 dark:bg-green-950/20'
      case 'error':
        return 'border-red-300 dark:border-red-700 bg-red-50/50 dark:bg-red-950/20'
      default:
        return 'border-zinc-300 dark:border-zinc-700 bg-zinc-50/50 dark:bg-zinc-950/20'
    }
  }

  return (
    <div className={`border rounded-md overflow-hidden ${statusColor()}`}>
      {/* Tool header */}
      <button
        onClick={() => setShowDetails(!showDetails)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs hover:opacity-80 transition-opacity"
      >
        {statusIcon()}
        <span className="font-mono font-medium text-zinc-700 dark:text-zinc-300">
          {tool.name}
        </span>

        {tool.retries && tool.retries > 0 && (
          <span className="flex items-center gap-1 px-1.5 py-0.5 bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300 rounded text-[10px]">
            <FaRedo size={7} />
            {tool.retries} {tool.retries === 1 ? 'retry' : 'retries'}
          </span>
        )}

        {tool.duration !== undefined && (
          <span className="ml-auto text-[10px] text-zinc-500 dark:text-zinc-400">
            {tool.duration}ms
          </span>
        )}

        {showDetails ? <FaChevronDown size={8} className="text-zinc-400" /> : <FaChevronRight size={8} className="text-zinc-400" />}
      </button>

      {/* Tool details */}
      {showDetails && (
        <div className="px-2.5 pb-2 space-y-1.5 text-xs">
          {/* Input */}
          <div>
            <div className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 mb-0.5">
              Input:
            </div>
            <pre className="bg-zinc-800 text-zinc-100 px-2 py-1.5 rounded text-[10px] overflow-x-auto font-mono">
              {JSON.stringify(tool.input, null, 2)}
            </pre>
          </div>

          {/* Output */}
          {tool.output && (
            <div>
              <div className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 mb-0.5">
                Output:
              </div>
              <pre className="bg-zinc-800 text-zinc-100 px-2 py-1.5 rounded text-[10px] overflow-x-auto font-mono max-h-40 overflow-y-auto">
                {typeof tool.output === 'string' ? tool.output : JSON.stringify(tool.output, null, 2)}
              </pre>
            </div>
          )}

          {/* Error */}
          {tool.error && (
            <div>
              <div className="text-[10px] font-semibold text-red-600 dark:text-red-400 mb-0.5">
                Error:
              </div>
              <pre className="bg-red-900/20 text-red-700 dark:text-red-300 px-2 py-1.5 rounded text-[10px] overflow-x-auto font-mono">
                {tool.error}
              </pre>
            </div>
          )}

          {/* Timing */}
          {tool.startTime && (
            <div className="text-[10px] text-zinc-500 dark:text-zinc-400 pt-1">
              Started: {new Date(tool.startTime).toLocaleTimeString()}
              {tool.endTime && ` → Ended: ${new Date(tool.endTime).toLocaleTimeString()}`}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
