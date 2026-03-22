import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, Paperclip, Mic, Sparkles } from 'lucide-react'

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
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
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
    <div className="p-4 border-t border-white/[0.06] bg-slate-900/60 backdrop-blur-xl">
      <form
        onSubmit={(e) => { e.preventDefault(); submit() }}
        className={`relative flex items-end gap-3 p-1.5 rounded-2xl border transition-all duration-300 ${
          isFocused
            ? 'bg-white/[0.04] border-indigo-500/30 shadow-lg shadow-indigo-500/10'
            : 'bg-white/[0.02] border-white/[0.06] hover:border-white/[0.1]'
        }`}
      >
        {/* Attachment button (decorative) */}
        <button
          type="button"
          className="flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center text-white/30 hover:text-white/60 hover:bg-white/[0.05] transition-all duration-200"
          title="Attach file (coming soon)"
        >
          <Paperclip className="h-4 w-4" />
        </button>

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
            placeholder={placeholder ?? 'Type your message...'}
            className="w-full resize-none px-2 py-2.5 bg-transparent
              text-white/90 placeholder:text-white/25 text-[14px] leading-relaxed
              focus:outline-none
              disabled:opacity-40 overflow-y-auto"
            style={{ minHeight: '44px', maxHeight: '160px' }}
            autoFocus
          />
        </div>

        {/* Voice button (decorative) */}
        <button
          type="button"
          className="flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center text-white/30 hover:text-white/60 hover:bg-white/[0.05] transition-all duration-200"
          title="Voice input (coming soon)"
        >
          <Mic className="h-4 w-4" />
        </button>

        {/* Send button */}
        <button
          type="submit"
          disabled={disabled || !hasContent}
          aria-label="Send message"
          className={`flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-300
            ${hasContent && !disabled
              ? 'bg-gradient-to-br from-indigo-500 via-violet-500 to-purple-600 text-white shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40 hover:scale-105 active:scale-95'
              : 'bg-white/[0.05] text-white/20 cursor-not-allowed'
            }`}
        >
          {disabled ? (
            <Sparkles className="h-4 w-4 animate-pulse" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </button>
      </form>

      {/* Helper text */}
      <div className="flex items-center justify-between mt-2 px-2">
        <p className="text-[10px] text-white/20">
          Press <kbd className="px-1 py-0.5 rounded bg-white/5 border border-white/10 font-mono">Enter</kbd> to send, <kbd className="px-1 py-0.5 rounded bg-white/5 border border-white/10 font-mono">Shift+Enter</kbd> for newline
        </p>
        <p className="text-[10px] text-white/20">
          {value.length > 0 && `${value.length} chars`}
        </p>
      </div>
    </div>
  )
}
