import { create } from 'zustand'
import { Message } from '../types/agent'

interface ChatStore {
  messages: Message[]
  isLoading: boolean
  addMessage: (message: Message) => void
  setMessages: (messages: Message[]) => void
  setLoading: (loading: boolean) => void
  clearMessages: () => void
  loadFromStorage: () => void
  saveToStorage: () => void
}

const CHAT_STORAGE_KEY = 'chatHistory'

export const useChatStore = create<ChatStore>((set, get) => ({
  messages: [],
  isLoading: false,

  addMessage: (message: Message) => {
    set((state) => ({
      messages: [...state.messages, message],
    }))
    // Auto-save to storage
    setTimeout(() => get().saveToStorage(), 0)
  },

  setMessages: (messages: Message[]) => {
    set({ messages })
    setTimeout(() => get().saveToStorage(), 0)
  },

  setLoading: (loading: boolean) => {
    set({ isLoading: loading })
  },

  clearMessages: () => {
    set({ messages: [] })
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem(CHAT_STORAGE_KEY)
    }
  },

  loadFromStorage: () => {
    if (typeof localStorage === 'undefined') return

    try {
      const stored = localStorage.getItem(CHAT_STORAGE_KEY)
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

  saveToStorage: () => {
    if (typeof localStorage === 'undefined') return

    try {
      const state = get()
      localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(state.messages))
    } catch (error) {
      console.error('Failed to save chat history:', error)
    }
  },
}))
