import { useState, useEffect } from 'react'
import { ChevronDown, ChevronRight, Brain, ListOrdered, Lightbulb, CheckCircle, Route, Sparkles, Clock, TrendingUp } from 'lucide-react'
import { ThinkingStep } from '@/shared/types/agent'

interface ThinkingSectionProps {
  thinking?: ThinkingStep[]
  plan?: string[]
  route?: string
  autoExpand?: boolean  // Auto-expand for complex queries
}

export default function ThinkingSection({ thinking, plan, route, autoExpand = false }: ThinkingSectionProps) {
  // Auto-expand if more than 2 steps or if autoExpand is true
  const shouldAutoExpand = autoExpand || (thinking && thinking.length > 2) || (plan && plan.length > 2)
  const [isExpanded, setIsExpanded] = useState(shouldAutoExpand)

  // Re-expand when new content arrives
  useEffect(() => {
    if (shouldAutoExpand && !isExpanded) {
      setIsExpanded(true)
    }
  }, [thinking?.length, plan?.length])

  if ((!thinking || thinking.length === 0) && (!plan || plan.length === 0)) return null

  const hasContent = (thinking && thinking.length > 0) || (plan && plan.length > 0)
  if (!hasContent) return null

  // Calculate stats
  const thinkingCount = thinking?.length || 0
  const planCount = plan?.length || 0
  const complexity = thinkingCount + planCount > 5 ? 'high' : thinkingCount + planCount > 2 ? 'medium' : 'low'

  return (
    <div className="mt-4 rounded-xl border border-secondary/30 overflow-hidden bg-gradient-to-br from-secondary/12 to-primary/10 backdrop-blur-sm shadow-lg">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2.5 px-4 py-3.5 text-xs font-medium text-secondary hover:bg-surface-container-high/40 transition-colors group"
      >
        <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-secondary/20 group-hover:bg-secondary/30 transition-colors">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-secondary" />
          ) : (
            <ChevronRight className="h-4 w-4 text-secondary" />
          )}
        </div>
        <Brain className="h-4.5 w-4.5 text-secondary" />
        <span className="font-bold text-sm">Reasoning Process</span>

        {/* Complexity indicator */}
        {complexity !== 'low' && (
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[9px] font-bold uppercase tracking-wider border ${
            complexity === 'high'
              ? 'bg-error/15 text-error border-error/30'
              : 'bg-tertiary/15 text-tertiary border-tertiary/30'
          }`}>
            <TrendingUp className="h-3 w-3" />
            {complexity} complexity
          </span>
        )}

        {/* Route badge */}
        {route && (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-primary/15 text-primary rounded-lg text-[10px] font-mono font-bold border border-primary/20">
            <Route className="h-3 w-3" />
            {route.replace('_', ' ')}
          </span>
        )}

        {/* Count badges */}
        <div className="flex gap-2 ml-auto">
          {plan && plan.length > 0 && (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 bg-tertiary/15 text-tertiary rounded-md text-[10px] font-bold border border-tertiary/10">
              <ListOrdered className="h-3 w-3" />
              {plan.length} steps planned
            </span>
          )}
          {thinking && thinking.length > 0 && (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 bg-secondary/15 text-secondary rounded-md text-[10px] font-bold border border-secondary/10">
              <Sparkles className="h-3 w-3" />
              {thinking.length} thoughts
            </span>
          )}
        </div>
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-4 pb-4 space-y-4">
          {/* Plan section */}
          {plan && plan.length > 0 && (
            <div className="p-4 rounded-xl bg-tertiary/8 border border-tertiary/15 shadow-sm">
              <div className="flex items-center gap-2 mb-3 text-[11px] font-bold text-tertiary uppercase tracking-wider">
                <ListOrdered className="h-4 w-4" />
                Multi-Step Execution Plan
              </div>
              <ol className="space-y-2.5">
                {plan.map((step, idx) => (
                  <li
                    key={idx}
                    className="flex gap-3 text-sm text-on-surface group"
                  >
                    <span className="flex-shrink-0 w-6 h-6 rounded-full bg-tertiary/25 text-tertiary text-[11px] font-bold flex items-center justify-center shadow-sm group-hover:scale-110 transition-transform">
                      {idx + 1}
                    </span>
                    <span className="pt-0.5 leading-relaxed">{step}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Thinking steps */}
          {thinking && thinking.length > 0 && (
            <div className="space-y-2.5">
              <div className="flex items-center gap-2 mb-3 text-[11px] font-bold text-secondary uppercase tracking-wider">
                <Lightbulb className="h-4 w-4" />
                Step-by-Step Reasoning
              </div>
              {thinking.map((step, idx) => (
                <div
                  key={idx}
                  className="p-3.5 rounded-xl bg-surface-container-lowest/40 border border-outline-variant/20 hover:border-secondary/30 transition-all hover:shadow-lg group"
                >
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 mt-0.5">
                      {step.type === 'plan' && (
                        <div className="w-6 h-6 rounded-lg bg-tertiary/25 flex items-center justify-center shadow-sm group-hover:scale-110 transition-transform">
                          <ListOrdered className="h-3.5 w-3.5 text-tertiary" />
                        </div>
                      )}
                      {step.type === 'reasoning' && (
                        <div className="w-6 h-6 rounded-lg bg-primary/25 flex items-center justify-center shadow-sm group-hover:scale-110 transition-transform">
                          <Brain className="h-3.5 w-3.5 text-primary" />
                        </div>
                      )}
                      {step.type === 'synthesis' && (
                        <div className="w-6 h-6 rounded-lg bg-secondary/25 flex items-center justify-center shadow-sm group-hover:scale-110 transition-transform">
                          <CheckCircle className="h-3.5 w-3.5 text-secondary" />
                        </div>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1.5 text-[10px] text-on-surface-variant/80">
                        <span className="font-semibold text-on-surface capitalize px-2 py-0.5 bg-surface-container/50 rounded">
                          {step.type}
                        </span>
                        <span>•</span>
                        <Clock className="h-3 w-3" />
                        <span>{new Date(step.timestamp).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-sm text-on-surface leading-relaxed font-medium">
                        {step.step}
                      </p>
                      {step.result && (
                        <div className="mt-2.5 pt-2.5 border-t border-outline-variant/20">
                          <div className="flex items-center gap-1.5 text-[10px] font-bold text-secondary mb-1.5 uppercase tracking-wide">
                            <CheckCircle className="h-3 w-3" />
                            Result
                          </div>
                          <p className="text-sm text-on-surface-variant bg-surface-container/40 px-3 py-2 rounded-lg">
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
