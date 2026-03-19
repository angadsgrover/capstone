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
      className="flex items-end gap-2 p-3 border-t border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900"
    >
      <textarea
        ref={textareaRef}
        rows={1}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={placeholder ?? 'Type your message… (Enter to send, Shift+Enter for newline)'}
        className="flex-1 resize-none px-4 py-3 rounded-2xl bg-zinc-100 dark:bg-zinc-800
          text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 text-sm
          focus:outline-none focus:ring-2 focus:ring-blue-500
          disabled:opacity-50 leading-relaxed overflow-y-auto"
        style={{ minHeight: '44px' }}
        autoFocus
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        aria-label="Send message"
        className="flex-shrink-0 w-11 h-11 rounded-full bg-blue-500 hover:bg-blue-600
          disabled:opacity-40 text-white flex items-center justify-center
          transition-colors shadow-sm"
      >
        <FaPaperPlane size={14} className={disabled ? 'animate-pulse' : ''} />
      </button>
    </form>
  )
}
