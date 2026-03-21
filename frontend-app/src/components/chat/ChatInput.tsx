import { useState, useRef, useEffect, useCallback } from 'react'
import { FaPaperPlane } from 'react-icons/fa'

interface ChatInputProps {
  onSend: (text: string) => void
  disabled?: boolean
  placeholder?: string
}

export default function ChatInput({ onSend, disabled, placeholder }: ChatInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-resize textarea up to ~6 lines
  const resize = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 144)}px`
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

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); submit() }}
      className="flex items-end gap-3 p-4 border-t border-white/[0.06] bg-white/[0.02]"
    >
      <textarea
        ref={textareaRef}
        rows={1}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={placeholder ?? 'Type your message... (Enter to send, Shift+Enter for newline)'}
        className="flex-1 resize-none px-4 py-3 rounded-2xl bg-white/[0.05] border border-white/[0.08]
          text-white/90 placeholder:text-white/30 text-sm
          focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/50
          disabled:opacity-40 leading-relaxed overflow-y-auto backdrop-blur-sm
          transition-all duration-200"
        style={{ minHeight: '48px' }}
        autoFocus
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        aria-label="Send message"
        className="flex-shrink-0 w-12 h-12 rounded-2xl bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500
          hover:shadow-lg hover:shadow-indigo-500/30 hover:scale-[1.02]
          disabled:opacity-30 disabled:hover:scale-100 disabled:hover:shadow-none
          text-white flex items-center justify-center
          transition-all duration-200 shadow-lg shadow-indigo-500/20"
      >
        <FaPaperPlane size={14} className={disabled ? 'animate-pulse' : ''} />
      </button>
    </form>
  )
}
