import type { AgentResponse } from '../types/agent'
import type { AgentApiRawResponse } from '../types/api'

interface LangChainRunResponse {
  output?: {
    output?: string
    response?: string
    [key: string]: unknown
  }
  error?: string
  [key: string]: unknown
}

const LANGCHAIN_BASE_URL = import.meta.env.VITE_LANGCHAIN_BASE_URL
const LANGCHAIN_RUN_ENDPOINT = import.meta.env.VITE_LANGCHAIN_RUN_ENDPOINT ?? '/runs/wait'
const LANGCHAIN_ASSISTANT_ID = import.meta.env.VITE_LANGCHAIN_ASSISTANT_ID
const LANGCHAIN_API_KEY = import.meta.env.VITE_LANGCHAIN_API_KEY
const LANGCHAIN_ENABLED = import.meta.env.VITE_LANGCHAIN_ENABLED === 'true'

function normalizePath(baseUrl: string, endpoint: string): string {
  const normalizedBase = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl
  const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`
  return `${normalizedBase}${normalizedEndpoint}`
}

export const langchainService = {
  isEnabled(): boolean {
    return Boolean(LANGCHAIN_ENABLED && LANGCHAIN_BASE_URL && LANGCHAIN_ASSISTANT_ID)
  },

  async sendMessage(input: string): Promise<AgentResponse> {
    if (!this.isEnabled()) {
      throw new Error('LangChain integration is not enabled')
    }

    const url = normalizePath(LANGCHAIN_BASE_URL!, LANGCHAIN_RUN_ENDPOINT)

    const body = {
      assistant_id: LANGCHAIN_ASSISTANT_ID,
      input: {
        messages: [
          {
            role: 'user',
            content: input,
          },
        ],
      },
    }

    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    }

    if (LANGCHAIN_API_KEY) {
      headers.Authorization = `Bearer ${LANGCHAIN_API_KEY}`
    }

    const res = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    })

    if (!res.ok) {
      throw new Error(`LangChain error: ${res.status} ${res.statusText}`)
    }

    const data = (await res.json()) as LangChainRunResponse
    if (data.error) {
      throw new Error(data.error)
    }

    const outputText = data.output?.output ?? data.output?.response
    if (typeof outputText !== 'string') {
      return {
        response: JSON.stringify(data),
        status: 'success',
        data: data as AgentApiRawResponse,
      }
    }

    return {
      response: outputText,
      status: 'success',
      data: data as AgentApiRawResponse,
    }
  },
}
