import { useState, useRef, useEffect, useCallback } from 'react'
import MaterialIcon from '@/components/ui/MaterialIcon'
import { cn } from '@/lib/utils'

interface ChatInputProps {
  onSend: (text: string) => void
  disabled?: boolean
  placeholder?: string
}

export default function ChatInput({ onSend, disabled, placeholder }: ChatInputProps) {
  const [value, setValue] = useState('')
  const [isFocused, setIsFocused] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const resize = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [])

  useEffect(() => {
    resize()
  }, [value, resize])

  const submit = useCallback(() => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
  }, [value, disabled, onSend])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const hasContent = value.trim().length > 0

  return (
    <div className="relative">
      {/* Floating glow effect */}
      <div className={cn(
        "absolute -inset-0.5 bg-gradient-to-r from-secondary/20 to-primary/20 rounded-2xl blur opacity-0 transition duration-500",
        isFocused && "opacity-60"
      )} />

      <form
        onSubmit={(e) => { e.preventDefault(); submit() }}
        className={cn(
          "relative flex items-end gap-3 p-3 rounded-2xl border transition-all duration-300",
          "bg-surface-container-highest/60 backdrop-blur-xl shadow-2xl",
          isFocused
            ? "border-secondary/50 shadow-secondary/10 scale-[1.01]"
            : "border-outline-variant/20 hover:border-outline-variant/40 hover:scale-[1.005]"
        )}
      >
        {/* Textarea */}
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            disabled={disabled}
            placeholder={placeholder ?? 'Ask about aviation weather...'}
            className={cn(
              "w-full resize-none px-3 py-3 bg-transparent text-on-surface placeholder:text-on-surface-variant/40",
              "text-sm leading-relaxed focus:outline-none overflow-y-auto",
              disabled && "opacity-40 cursor-not-allowed"
            )}
            style={{ minHeight: '44px', maxHeight: '200px' }}
            autoFocus
          />
        </div>

        {/* Send button */}
        <button
          type="submit"
          disabled={disabled || !hasContent}
          aria-label="Send message"
          className={cn(
            "flex-shrink-0 h-11 px-5 rounded-xl flex items-center justify-center gap-2 transition-all duration-300 font-medium text-sm uppercase tracking-wider",
            hasContent && !disabled
              ? "user-gradient text-on-primary-container shadow-lg shadow-primary/20 hover:shadow-primary/30 hover:scale-105 hover:brightness-110 active:scale-95"
              : "bg-surface-container text-on-surface-variant/30 cursor-not-allowed"
          )}
        >
          {disabled ? (
            <>
              <MaterialIcon icon="pending" className="text-base animate-spin" />
              <span className="hidden sm:inline">Processing</span>
            </>
          ) : (
            <>
              <MaterialIcon icon="send" className="text-base" filled={hasContent} />
              <span className="hidden sm:inline">Send</span>
            </>
          )}
        </button>
      </form>

      {/* Helper text */}
      <div className="flex items-center justify-between mt-3 px-2">
        <div className="flex items-center gap-4 text-[10px] text-on-surface-variant/60">
          <span className="flex items-center gap-1.5">
            <kbd className="px-1.5 py-0.5 rounded bg-surface-container border border-outline-variant/20 font-mono">Enter</kbd>
            to send
          </span>
          <span className="flex items-center gap-1.5">
            <kbd className="px-1.5 py-0.5 rounded bg-surface-container border border-outline-variant/20 font-mono">Shift+Enter</kbd>
            newline
          </span>
        </div>
        {value.length > 0 && (
          <p className="text-[10px] text-on-surface-variant/60 font-mono">
            {value.length} chars
          </p>
        )}
      </div>
    </div>
  )
}
