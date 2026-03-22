import { useState } from 'react'
import { ChevronDown, ChevronRight, Brain, ListOrdered, Lightbulb, CheckCircle, Route, Sparkles } from 'lucide-react'
import { ThinkingStep } from '@/shared/types/agent'

interface ThinkingSectionProps {
  thinking?: ThinkingStep[]
  plan?: string[]
  route?: string
}

export default function ThinkingSection({ thinking, plan, route }: ThinkingSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  if ((!thinking || thinking.length === 0) && (!plan || plan.length === 0)) return null

  const hasContent = (thinking && thinking.length > 0) || (plan && plan.length > 0)
  if (!hasContent) return null

  return (
    <div className="mt-4 rounded-xl border border-indigo-500/20 overflow-hidden bg-gradient-to-br from-indigo-500/5 to-purple-500/5 backdrop-blur-sm">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2.5 px-4 py-3 text-xs font-medium text-indigo-300 hover:bg-white/[0.02] transition-colors"
      >
        <div className="flex items-center justify-center w-6 h-6 rounded-lg bg-indigo-500/15">
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-indigo-400" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-indigo-400" />
          )}
        </div>
        <Brain className="h-4 w-4 text-indigo-400" />
        <span className="font-semibold">Reasoning</span>

        {/* Route badge */}
        {route && (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-violet-500/15 text-violet-300 rounded-lg text-[10px] font-mono font-medium border border-violet-500/20">
            <Route className="h-3 w-3" />
            {route}
          </span>
        )}

        {/* Count badges */}
        <div className="flex gap-2 ml-auto">
          {plan && plan.length > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-purple-500/15 text-purple-300 rounded-md text-[10px] font-medium border border-purple-500/10">
              <ListOrdered className="h-3 w-3" />
              {plan.length} steps
            </span>
          )}
          {thinking && thinking.length > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-emerald-500/15 text-emerald-300 rounded-md text-[10px] font-medium border border-emerald-500/10">
              <Sparkles className="h-3 w-3" />
              {thinking.length}
            </span>
          )}
        </div>
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-4 pb-4 space-y-4">
          {/* Plan section */}
          {plan && plan.length > 0 && (
            <div className="p-3 rounded-lg bg-purple-500/5 border border-purple-500/10">
              <div className="flex items-center gap-2 mb-3 text-[11px] font-semibold text-purple-400 uppercase tracking-wider">
                <ListOrdered className="h-3.5 w-3.5" />
                Execution Plan
              </div>
              <ol className="space-y-2">
                {plan.map((step, idx) => (
                  <li
                    key={idx}
                    className="flex gap-3 text-sm text-white/70"
                  >
                    <span className="flex-shrink-0 w-5 h-5 rounded-full bg-purple-500/20 text-purple-400 text-[10px] font-bold flex items-center justify-center">
                      {idx + 1}
                    </span>
                    <span className="pt-0.5">{step}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Thinking steps */}
          {thinking && thinking.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 mb-3 text-[11px] font-semibold text-emerald-400 uppercase tracking-wider">
                <Lightbulb className="h-3.5 w-3.5" />
                Reasoning Steps
              </div>
              {thinking.map((step, idx) => (
                <div
                  key={idx}
                  className="p-3 rounded-lg bg-white/[0.02] border border-white/[0.06] hover:border-white/[0.1] transition-colors"
                >
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 mt-0.5">
                      {step.type === 'plan' && (
                        <div className="w-5 h-5 rounded-lg bg-purple-500/20 flex items-center justify-center">
                          <ListOrdered className="h-3 w-3 text-purple-400" />
                        </div>
                      )}
                      {step.type === 'reasoning' && (
                        <div className="w-5 h-5 rounded-lg bg-indigo-500/20 flex items-center justify-center">
                          <Brain className="h-3 w-3 text-indigo-400" />
                        </div>
                      )}
                      {step.type === 'synthesis' && (
                        <div className="w-5 h-5 rounded-lg bg-emerald-500/20 flex items-center justify-center">
                          <CheckCircle className="h-3 w-3 text-emerald-400" />
                        </div>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1 text-[10px] text-white/40">
                        <span className="font-medium text-white/60 capitalize">{step.type}</span>
                        <span>·</span>
                        <span>{new Date(step.timestamp).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-sm text-white/80 leading-relaxed">
                        {step.step}
                      </p>
                      {step.result && (
                        <div className="mt-2 pt-2 border-t border-white/[0.06]">
                          <div className="text-[10px] font-semibold text-emerald-400/80 mb-1 uppercase tracking-wide">
                            Result
                          </div>
                          <p className="text-sm text-emerald-300/80">
                            {step.result}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
