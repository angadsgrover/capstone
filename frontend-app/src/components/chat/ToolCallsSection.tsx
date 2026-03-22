import { useState } from 'react'
import { ChevronDown, ChevronRight, Wrench, CheckCircle, AlertCircle, Loader2, RotateCcw, Clock, Zap } from 'lucide-react'
import { ToolCall } from '@/shared/types/agent'

interface ToolCallsSectionProps {
  toolCalls: ToolCall[]
}

export default function ToolCallsSection({ toolCalls }: ToolCallsSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!toolCalls || toolCalls.length === 0) return null

  const successCount = toolCalls.filter((t) => t.status === 'success').length
  const errorCount = toolCalls.filter((t) => t.status === 'error').length
  const runningCount = toolCalls.filter((t) => t.status === 'running').length

  return (
    <div className="mt-4 rounded-xl border border-secondary/20 overflow-hidden bg-gradient-to-br from-secondary/8 to-primary/8 backdrop-blur-sm">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2.5 px-4 py-3 text-xs font-medium text-secondary hover:bg-surface-container-high/40 transition-colors"
      >
        <div className="flex items-center justify-center w-6 h-6 rounded-lg bg-secondary/15">
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-secondary" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-secondary" />
          )}
        </div>
        <Wrench className="h-4 w-4 text-secondary" />
        <span className="font-semibold">Tools Used</span>
        <span className="text-secondary/70">({toolCalls.length})</span>

        <div className="flex gap-2 ml-auto">
          {runningCount > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-primary/15 text-primary rounded-md text-[10px] font-medium border border-primary/10 animate-pulse">
              <Loader2 className="h-3 w-3 animate-spin" />
              {runningCount}
            </span>
          )}
          {successCount > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-secondary/15 text-secondary rounded-md text-[10px] font-medium border border-secondary/10">
              <CheckCircle className="h-3 w-3" />
              {successCount}
            </span>
          )}
          {errorCount > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-error/15 text-error rounded-md text-[10px] font-medium border border-error/10">
              <AlertCircle className="h-3 w-3" />
              {errorCount}
            </span>
          )}
        </div>
      </button>

      {isExpanded && (
        <div className="px-4 pb-4 space-y-2">
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

  const statusConfig = {
    running: {
      icon: <Loader2 className="h-3.5 w-3.5 text-primary animate-spin" />,
      bg: 'bg-primary/10',
      border: 'border-primary/20',
    },
    success: {
      icon: <CheckCircle className="h-3.5 w-3.5 text-secondary" />,
      bg: 'bg-secondary/10',
      border: 'border-secondary/20',
    },
    error: {
      icon: <AlertCircle className="h-3.5 w-3.5 text-error" />,
      bg: 'bg-error/10',
      border: 'border-error/20',
    },
  }

  const status = tool.status ? (statusConfig[tool.status] || statusConfig.success) : statusConfig.success

  return (
    <div className={`rounded-xl border ${status.border} ${status.bg} overflow-hidden transition-all duration-200 ${showDetails ? 'ring-1 ring-outline-variant/20' : ''}`}>
      <button
        onClick={() => setShowDetails(!showDetails)}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-xs hover:bg-surface-container-high/30 transition-colors"
      >
        <div className="flex-shrink-0 w-6 h-6 rounded-lg bg-surface-container-high/70 flex items-center justify-center">
          {status.icon}
        </div>

        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span className="font-mono font-semibold text-on-surface truncate">
            {tool.name}
          </span>

          {tool.retries && tool.retries > 0 && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-tertiary/15 text-tertiary rounded text-[9px] font-medium">
              <RotateCcw className="h-2.5 w-2.5" />
              {tool.retries}
            </span>
          )}
        </div>

        {tool.duration !== undefined && (
          <span className="inline-flex items-center gap-1 text-[10px] text-on-surface-variant/80 font-mono">
            <Zap className="h-3 w-3" />
            {tool.duration}ms
          </span>
        )}

        <ChevronDown className={`h-3.5 w-3.5 text-on-surface-variant/70 transition-transform duration-200 ${showDetails ? 'rotate-180' : ''}`} />
      </button>

      {showDetails && (
        <div className="px-3 pb-3 space-y-3 border-t border-outline-variant/15">
          <div className="pt-3">
            <div className="text-[10px] font-semibold text-on-surface-variant uppercase tracking-wider mb-1.5">
              Input
            </div>
            <pre className="bg-surface-container-lowest/85 text-on-surface px-3 py-2 rounded-lg text-[11px] overflow-x-auto font-mono border border-outline-variant/15">
              {JSON.stringify(tool.input, null, 2)}
            </pre>
          </div>

          {tool.output && (
            <div>
              <div className="text-[10px] font-semibold text-secondary uppercase tracking-wider mb-1.5">
                Output
              </div>
              <pre className="bg-surface-container-lowest/85 text-on-surface px-3 py-2 rounded-lg text-[11px] overflow-x-auto font-mono max-h-32 overflow-y-auto border border-secondary/15">
                {typeof tool.output === 'string' ? tool.output : JSON.stringify(tool.output, null, 2)}
              </pre>
            </div>
          )}

          {tool.error && (
            <div>
              <div className="text-[10px] font-semibold text-error uppercase tracking-wider mb-1.5">
                Error
              </div>
              <pre className="bg-error/10 text-error px-3 py-2 rounded-lg text-[11px] overflow-x-auto font-mono border border-error/20">
                {tool.error}
              </pre>
            </div>
          )}

          {tool.startTime && (
            <div className="flex items-center gap-2 pt-2 border-t border-outline-variant/10 text-[10px] text-on-surface-variant/80">
              <Clock className="h-3 w-3" />
              <span>Started: {new Date(tool.startTime).toLocaleTimeString()}</span>
              {tool.endTime && (
                <>
                  <span>→</span>
                  <span>Ended: {new Date(tool.endTime).toLocaleTimeString()}</span>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
