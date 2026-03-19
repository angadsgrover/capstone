import { AgentRequest, AgentResponse } from '../types/agent'

const API_BASE = import.meta.env.VITE_AGENT_API_URL ?? 'http://localhost:8000'

export const agentService = {
  /**
   * Send a message to the agent and get a response
   */
  async sendMessage(input: string): Promise<AgentResponse> {
    const req: AgentRequest = { input }
    const res = await fetch(`${API_BASE}/api/agent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    })

    if (!res.ok) {
      throw new Error(`Agent error: ${res.statusText}`)
    }

    const data = await res.json()
    return normalizeResponse(data)
  },

  /**
   * Execute a workflow
   */
  async executeWorkflow(inputs: Record<string, any>): Promise<AgentResponse> {
    const res = await fetch(`${API_BASE}/api/agent/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(inputs),
    })

    if (!res.ok) {
      throw new Error(`Execution error: ${res.statusText}`)
    }

    const data = await res.json()
    return normalizeResponse(data)
  },

  async getAirportMap(limit = 12): Promise<any> {
    const res = await fetch(`${API_BASE}/api/visualizations/airport-map?limit=${limit}`)
    if (!res.ok) throw new Error(`Airport map error: ${res.statusText}`)
    return res.json()
  },

  async getWeatherTrends(icaos: string[], hours = 72): Promise<any> {
    const query = encodeURIComponent(icaos.join(','))
    const res = await fetch(`${API_BASE}/api/visualizations/weather-trends?icaos=${query}&hours=${hours}`)
    if (!res.ok) throw new Error(`Weather trends error: ${res.statusText}`)
    return res.json()
  },

  async getFlightPaths(limit = 8): Promise<any> {
    const res = await fetch(`${API_BASE}/api/visualizations/flight-paths?limit=${limit}`)
    if (!res.ok) throw new Error(`Flight paths error: ${res.statusText}`)
    return res.json()
  },

  async getSafetyHeatmap(limit = 20): Promise<any> {
    const res = await fetch(`${API_BASE}/api/visualizations/safety-heatmap?limit=${limit}`)
    if (!res.ok) throw new Error(`Safety heatmap error: ${res.statusText}`)
    return res.json()
  },
}

/**
 * Normalize response formats from different endpoints
 */
function normalizeResponse(data: any): AgentResponse {
  if (!data || typeof data !== 'object') {
    return {
      response: String(data),
      status: 'error',
    }
  }

  // Check for common response patterns
  if (data.response) {
    const { response, status, ...rest } = data
    return {
      response,
      status: status || 'success',
      data: {
        ...(data.data || {}),
        ...rest,
      },
    }
  }

  if (data.final_response) {
    return {
      response: data.final_response,
      status: 'success',
      data,
    }
  }

  if (data.result) {
    return {
      response: typeof data.result === 'string' ? data.result : JSON.stringify(data.result),
      status: 'success',
      data,
    }
  }

  if (data.output) {
    return {
      response: data.output,
      status: 'success',
      data,
    }
  }

  return {
    response: JSON.stringify(data),
    status: 'success',
    data,
  }
}
