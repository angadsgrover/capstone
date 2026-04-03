import { create } from 'zustand'
import { Message } from '../types/agent'

interface ChatStore {
  messages: Message[]
  isLoading: boolean
  addMessage: (message: Message, sessionId?: string) => void
  setMessages: (messages: Message[], sessionId?: string) => void
  setLoading: (loading: boolean) => void
  clearMessages: (sessionId?: string) => void
  loadFromStorage: (sessionId?: string) => void
  saveToStorage: (sessionId?: string) => void
}

const CHAT_STORAGE_PREFIX = 'chatHistory'
const CHAT_SESSION_KEY = 'chatSessionId'

function getActiveSessionId(): string {
  if (typeof window === 'undefined' || typeof localStorage === 'undefined') {
    return 'default'
  }
  return localStorage.getItem(CHAT_SESSION_KEY) || 'default'
}

function getSessionStorageKey(sessionId?: string): string {
  const safeSessionId = sessionId || getActiveSessionId()
  return `${CHAT_STORAGE_PREFIX}:${safeSessionId}`
}

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  isLoading: false,

  addMessage: (message: Message, sessionId?: string) => {
    set((state) => ({
      messages: [...state.messages, message],
    }))
    // Auto-save to storage
    setTimeout(() => get().saveToStorage(sessionId), 0)
  },

  setMessages: (messages: Message[], sessionId?: string) => {
    set({ messages })
    setTimeout(() => get().saveToStorage(sessionId), 0)
  },

  setLoading: (loading: boolean) => {
    set({ isLoading: loading })
  },

  clearMessages: (sessionId?: string) => {
    set({ messages: [] })
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(getSessionStorageKey(sessionId))
    }
  },

  loadFromStorage: (sessionId?: string) => {
    if (typeof localStorage === 'undefined') return

    try {
      const stored = localStorage.getItem(getSessionStorageKey(sessionId))
      if (stored) {
        const parsed = JSON.parse(stored)
        const messages = parsed.map((msg: any) => ({
          ...msg,
          timestamp: new Date(msg.timestamp),
          thinking: Array.isArray(msg.thinking)
            ? msg.thinking.map((t: any) => ({ ...t, timestamp: new Date(t.timestamp) }))
            : undefined,
          toolCalls: Array.isArray(msg.toolCalls)
            ? msg.toolCalls.map((tool: any) => ({
                ...tool,
                startTime: tool.startTime ? new Date(tool.startTime) : undefined,
                endTime: tool.endTime ? new Date(tool.endTime) : undefined,
              }))
            : undefined,
        }))
        set({ messages })
      }
    } catch (error) {
      console.error('Failed to load chat history:', error)
    }
  },

  saveToStorage: (sessionId?: string) => {
    if (typeof localStorage === 'undefined') return

    try {
      const state = get()
      localStorage.setItem(getSessionStorageKey(sessionId), JSON.stringify(state.messages))
    } catch (error) {
      console.error('Failed to save chat history:', error)
    }
  },
}))
