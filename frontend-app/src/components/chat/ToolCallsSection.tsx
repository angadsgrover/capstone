import { useState } from 'react'
import { ChevronDown, ChevronRight, Wrench, CheckCircle, AlertCircle, Loader2, RotateCcw, Clock, Zap } from 'lucide-react'
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
    <div className="mt-4 rounded-xl border border-amber-500/20 overflow-hidden bg-gradient-to-br from-amber-500/5 to-orange-500/5 backdrop-blur-sm">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2.5 px-4 py-3 text-xs font-medium text-amber-300 hover:bg-white/[0.02] transition-colors"
      >
        <div className="flex items-center justify-center w-6 h-6 rounded-lg bg-amber-500/15">
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-amber-400" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-amber-400" />
          )}
        </div>
        <Wrench className="h-4 w-4 text-amber-400" />
        <span className="font-semibold">Tools Used</span>
        <span className="text-amber-400/60">({toolCalls.length})</span>

        {/* Status badges */}
        <div className="flex gap-2 ml-auto">
          {runningCount > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-500/15 text-blue-300 rounded-md text-[10px] font-medium border border-blue-500/10 animate-pulse">
              <Loader2 className="h-3 w-3 animate-spin" />
              {runningCount}
            </span>
          )}
          {successCount > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-emerald-500/15 text-emerald-300 rounded-md text-[10px] font-medium border border-emerald-500/10">
              <CheckCircle className="h-3 w-3" />
              {successCount}
            </span>
          )}
          {errorCount > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-red-500/15 text-red-300 rounded-md text-[10px] font-medium border border-red-500/10">
              <AlertCircle className="h-3 w-3" />
              {errorCount}
            </span>
          )}
        </div>
      </button>

      {/* Expanded content */}
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
      icon: <Loader2 className="h-3.5 w-3.5 text-blue-400 animate-spin" />,
      bg: 'bg-blue-500/10',
      border: 'border-blue-500/20',
      glow: 'shadow-blue-500/10'
    },
    success: {
      icon: <CheckCircle className="h-3.5 w-3.5 text-emerald-400" />,
      bg: 'bg-emerald-500/10',
      border: 'border-emerald-500/20',
      glow: ''
    },
    error: {
      icon: <AlertCircle className="h-3.5 w-3.5 text-red-400" />,
      bg: 'bg-red-500/10',
      border: 'border-red-500/20',
      glow: ''
    }
  }

  const status = tool.status ? (statusConfig[tool.status] || statusConfig.success) : statusConfig.success

  return (
    <div className={`rounded-xl border ${status.border} ${status.bg} overflow-hidden transition-all duration-200 ${showDetails ? 'ring-1 ring-white/10' : ''}`}>
      {/* Tool header */}
      <button
        onClick={() => setShowDetails(!showDetails)}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-xs hover:bg-white/[0.02] transition-colors"
      >
        <div className="flex-shrink-0 w-6 h-6 rounded-lg bg-white/[0.05] flex items-center justify-center">
          {status.icon}
        </div>

        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span className="font-mono font-semibold text-white/90 truncate">
            {tool.name}
          </span>

          {tool.retries && tool.retries > 0 && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-orange-500/15 text-orange-300 rounded text-[9px] font-medium">
              <RotateCcw className="h-2.5 w-2.5" />
              {tool.retries}
            </span>
          )}
        </div>

        {tool.duration !== undefined && (
          <span className="inline-flex items-center gap-1 text-[10px] text-white/40 font-mono">
            <Zap className="h-3 w-3" />
            {tool.duration}ms
          </span>
        )}

        <ChevronDown className={`h-3.5 w-3.5 text-white/30 transition-transform duration-200 ${showDetails ? 'rotate-180' : ''}`} />
      </button>

      {/* Tool details */}
      {showDetails && (
        <div className="px-3 pb-3 space-y-3 border-t border-white/[0.06]">
          {/* Input */}
          <div className="pt-3">
            <div className="text-[10px] font-semibold text-white/40 uppercase tracking-wider mb-1.5">
              Input
            </div>
            <pre className="bg-slate-950/60 text-white/80 px-3 py-2 rounded-lg text-[11px] overflow-x-auto font-mono border border-white/[0.06]">
              {JSON.stringify(tool.input, null, 2)}
            </pre>
          </div>

          {/* Output */}
          {tool.output && (
            <div>
              <div className="text-[10px] font-semibold text-emerald-400/80 uppercase tracking-wider mb-1.5">
                Output
              </div>
              <pre className="bg-slate-950/60 text-emerald-300/80 px-3 py-2 rounded-lg text-[11px] overflow-x-auto font-mono max-h-32 overflow-y-auto border border-emerald-500/10">
                {typeof tool.output === 'string' ? tool.output : JSON.stringify(tool.output, null, 2)}
              </pre>
            </div>
          )}

          {/* Error */}
          {tool.error && (
            <div>
              <div className="text-[10px] font-semibold text-red-400/80 uppercase tracking-wider mb-1.5">
                Error
              </div>
              <pre className="bg-red-950/30 text-red-300 px-3 py-2 rounded-lg text-[11px] overflow-x-auto font-mono border border-red-500/20">
                {tool.error}
              </pre>
            </div>
          )}

          {/* Timing */}
          {tool.startTime && (
            <div className="flex items-center gap-2 pt-2 border-t border-white/[0.04] text-[10px] text-white/30">
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
