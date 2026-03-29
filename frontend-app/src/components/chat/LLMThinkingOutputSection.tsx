import { useState } from 'react'
import { ChevronDown, ChevronRight, Sparkles, Brain, CheckCircle, ListOrdered, Clock } from 'lucide-react'
import { ThinkingStep } from '@/shared/types/agent'

interface LLMThinkingOutputSectionProps {
  thinking: ThinkingStep[]
}

export default function LLMThinkingOutputSection({ thinking }: LLMThinkingOutputSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!thinking || thinking.length === 0) return null

  return (
    <div className="mt-4 rounded-xl border border-primary/30 overflow-hidden bg-gradient-to-br from-primary/12 to-secondary/8 backdrop-blur-sm shadow-lg">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2.5 px-4 py-3.5 text-xs font-medium text-primary hover:bg-surface-container-high/40 transition-colors group"
      >
        <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-primary/20 group-hover:bg-primary/30 transition-colors">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-primary" />
          ) : (
            <ChevronRight className="h-4 w-4 text-primary" />
          )}
        </div>
        <Sparkles className="h-4.5 w-4.5 text-primary" />
        <span className="font-bold text-sm">LLM Thinking Output</span>
        <span className="text-primary/70 font-semibold">({thinking.length})</span>
      </button>

      {isExpanded && (
        <div className="px-4 pb-4 space-y-2.5">
          {thinking.map((step, idx) => {
            const typeLabel = step.type === 'plan'
              ? 'plan'
              : step.type === 'synthesis'
                ? 'synthesis'
                : 'reasoning'

            return (
              <div
                key={`${idx}-${step.type}-${step.step.slice(0, 24)}`}
                className="p-3.5 rounded-xl bg-surface-container-lowest/45 border border-outline-variant/20 hover:border-primary/30 transition-all"
              >
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 w-6 h-6 rounded-lg bg-primary/20 text-primary text-[11px] font-bold flex items-center justify-center shadow-sm">
                    {idx + 1}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center flex-wrap gap-2 mb-1.5 text-[10px] text-on-surface-variant/80">
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-surface-container/60 text-on-surface font-semibold capitalize">
                        {typeLabel === 'plan' && <ListOrdered className="h-3 w-3" />}
                        {typeLabel === 'reasoning' && <Brain className="h-3 w-3" />}
                        {typeLabel === 'synthesis' && <CheckCircle className="h-3 w-3" />}
                        {typeLabel}
                      </span>
                      <span>•</span>
                      <span className="inline-flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {new Date(step.timestamp).toLocaleTimeString()}
                      </span>
                    </div>

                    <p className="text-sm text-on-surface leading-relaxed">{step.step}</p>

                    {step.result && (
                      <p className="mt-2 text-sm text-on-surface-variant bg-surface-container/45 px-3 py-2 rounded-lg border border-outline-variant/15">
                        {step.result}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
