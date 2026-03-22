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
    <div className="mt-4 rounded-xl border border-primary/20 overflow-hidden bg-gradient-to-br from-primary/8 to-tertiary/8 backdrop-blur-sm">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2.5 px-4 py-3 text-xs font-medium text-primary hover:bg-surface-container-high/40 transition-colors"
      >
        <div className="flex items-center justify-center w-6 h-6 rounded-lg bg-primary/15">
          {isExpanded ? (
            <ChevronDown className="h-3.5 w-3.5 text-primary" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-primary" />
          )}
        </div>
        <Brain className="h-4 w-4 text-primary" />
        <span className="font-semibold">Reasoning</span>

        {/* Route badge */}
        {route && (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-tertiary/15 text-tertiary rounded-lg text-[10px] font-mono font-medium border border-tertiary/20">
            <Route className="h-3 w-3" />
            {route}
          </span>
        )}

        {/* Count badges */}
        <div className="flex gap-2 ml-auto">
          {plan && plan.length > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-tertiary/15 text-tertiary rounded-md text-[10px] font-medium border border-tertiary/10">
              <ListOrdered className="h-3 w-3" />
              {plan.length} steps
            </span>
          )}
          {thinking && thinking.length > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-secondary/15 text-secondary rounded-md text-[10px] font-medium border border-secondary/10">
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
            <div className="p-3 rounded-lg bg-tertiary/6 border border-tertiary/12">
              <div className="flex items-center gap-2 mb-3 text-[11px] font-semibold text-tertiary uppercase tracking-wider">
                <ListOrdered className="h-3.5 w-3.5" />
                Execution Plan
              </div>
              <ol className="space-y-2">
                {plan.map((step, idx) => (
                  <li
                    key={idx}
                    className="flex gap-3 text-sm text-on-surface"
                  >
                    <span className="flex-shrink-0 w-5 h-5 rounded-full bg-tertiary/20 text-tertiary text-[10px] font-bold flex items-center justify-center">
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
              <div className="flex items-center gap-2 mb-3 text-[11px] font-semibold text-secondary uppercase tracking-wider">
                <Lightbulb className="h-3.5 w-3.5" />
                Reasoning Steps
              </div>
              {thinking.map((step, idx) => (
                <div
                  key={idx}
                  className="p-3 rounded-lg bg-surface-container-lowest/30 border border-outline-variant/15 hover:border-outline-variant/35 transition-colors"
                >
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 mt-0.5">
                      {step.type === 'plan' && (
                        <div className="w-5 h-5 rounded-lg bg-tertiary/20 flex items-center justify-center">
                          <ListOrdered className="h-3 w-3 text-tertiary" />
                        </div>
                      )}
                      {step.type === 'reasoning' && (
                        <div className="w-5 h-5 rounded-lg bg-primary/20 flex items-center justify-center">
                          <Brain className="h-3 w-3 text-primary" />
                        </div>
                      )}
                      {step.type === 'synthesis' && (
                        <div className="w-5 h-5 rounded-lg bg-secondary/20 flex items-center justify-center">
                          <CheckCircle className="h-3 w-3 text-secondary" />
                        </div>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1 text-[10px] text-on-surface-variant/70">
                        <span className="font-medium text-on-surface-variant capitalize">{step.type}</span>
                        <span>·</span>
                        <span>{new Date(step.timestamp).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-sm text-on-surface leading-relaxed">
                        {step.step}
                      </p>
                      {step.result && (
                        <div className="mt-2 pt-2 border-t border-outline-variant/15">
                          <div className="text-[10px] font-semibold text-secondary mb-1 uppercase tracking-wide">
                            Result
                          </div>
                          <p className="text-sm text-on-surface">
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
