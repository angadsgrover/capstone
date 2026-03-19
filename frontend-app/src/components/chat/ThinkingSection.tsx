import { useState } from 'react'
import { FaChevronDown, FaChevronRight, FaBrain, FaListOl, FaLightbulb, FaCheckCircle } from 'react-icons/fa'
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
    <div className="mt-3 border border-indigo-200 dark:border-indigo-800 rounded-lg overflow-hidden bg-indigo-50/50 dark:bg-indigo-950/20">
      {/* Header - Collapsible */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100 dark:hover:bg-indigo-900/20 transition-colors"
      >
        {isExpanded ? <FaChevronDown size={10} /> : <FaChevronRight size={10} />}
        <FaBrain size={11} />
        <span>Thinking</span>

        {/* Route badge */}
        {route && (
          <span className="px-2 py-0.5 bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300 rounded text-[10px] font-mono">
            {route}
          </span>
        )}

        {/* Count badges */}
        <div className="flex gap-1.5 ml-auto">
          {plan && plan.length > 0 && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded text-[10px]">
              <FaListOl size={8} />
              {plan.length} steps
            </span>
          )}
          {thinking && thinking.length > 0 && (
            <span className="flex items-center gap-1 px-1.5 py-0.5 bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 rounded text-[10px]">
              <FaLightbulb size={8} />
              {thinking.length}
            </span>
          )}
        </div>
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-3 pb-3 space-y-3">
          {/* Plan section */}
          {plan && plan.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 mb-2 text-[10px] font-semibold text-purple-600 dark:text-purple-400">
                <FaListOl size={9} />
                Multi-Step Plan
              </div>
              <ol className="space-y-1.5 list-decimal list-inside">
                {plan.map((step, idx) => (
                  <li
                    key={idx}
                    className="text-xs text-zinc-700 dark:text-zinc-300 pl-2"
                  >
                    {step}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Thinking steps */}
          {thinking && thinking.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 mb-2 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
                <FaLightbulb size={9} />
                Reasoning Steps
              </div>
              {thinking.map((step, idx) => (
                <div
                  key={idx}
                  className="border border-zinc-200 dark:border-zinc-700 rounded-md p-2 bg-white/50 dark:bg-zinc-900/30"
                >
                  {/* Step header */}
                  <div className="flex items-start gap-2 mb-1">
                    <div className="flex-shrink-0 mt-0.5">
                      {step.type === 'plan' && <FaListOl className="text-purple-500" size={10} />}
                      {step.type === 'reasoning' && <FaBrain className="text-indigo-500" size={10} />}
                      {step.type === 'synthesis' && <FaCheckCircle className="text-green-500" size={10} />}
                    </div>
                    <div className="flex-1">
                      <div className="text-[10px] font-medium text-zinc-500 dark:text-zinc-400 mb-0.5">
                        {step.type.charAt(0).toUpperCase() + step.type.slice(1)}
                        {' · '}
                        <span className="text-zinc-400 dark:text-zinc-500">
                          {new Date(step.timestamp).toLocaleTimeString()}
                        </span>
                      </div>
                      <p className="text-xs text-zinc-700 dark:text-zinc-300 leading-relaxed">
                        {step.step}
                      </p>
                      {step.result && (
                        <div className="mt-1.5 pt-1.5 border-t border-zinc-200 dark:border-zinc-700">
                          <div className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400 mb-0.5">
                            Result:
                          </div>
                          <p className="text-xs text-green-700 dark:text-green-300">
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
