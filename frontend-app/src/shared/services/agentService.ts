import { AgentRequest, AgentResponse } from '../types/agent'
import {
  AgentApiRawResponse,
  AirportMapResponse,
  FlightPathsResponse,
  SafetyHeatmapResponse,
  WeatherTrendsResponse,
} from '../types/api'
import { langchainService } from './langchainService'

const API_BASE = import.meta.env.VITE_AGENT_API_URL ?? 'http://localhost:8000'

export const agentService = {
  /**
   * Send a message to the agent and get a response
   */
  async sendMessage(input: string): Promise<AgentResponse> {
    if (langchainService.isEnabled()) {
      try {
        return await langchainService.sendMessage(input)
      } catch (error) {
        console.warn('LangChain request failed; falling back to local agent API.', error)
      }
    }

    const req: AgentRequest = { input }
    const res = await fetch(`${API_BASE}/api/agent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    })

    if (!res.ok) {
      throw new Error(`Agent error: ${res.statusText}`)
    }

    const data = (await res.json()) as AgentApiRawResponse
    return normalizeResponse(data)
  },

  /**
   * Execute a workflow
   */
  async executeWorkflow(inputs: Record<string, unknown>): Promise<AgentResponse> {
    const res = await fetch(`${API_BASE}/api/agent/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(inputs),
    })

    if (!res.ok) {
      throw new Error(`Execution error: ${res.statusText}`)
    }

    const data = (await res.json()) as AgentApiRawResponse
    return normalizeResponse(data)
  },

  async getAirportMap(limit = 12): Promise<AirportMapResponse> {
    const res = await fetch(`${API_BASE}/api/visualizations/airport-map?limit=${limit}`)
    if (!res.ok) throw new Error(`Airport map error: ${res.statusText}`)
    const data = (await res.json()) as Partial<AirportMapResponse>
    return {
      airports: Array.isArray(data.airports) ? data.airports : [],
    }
  },

  async getWeatherTrends(icaos: string[], hours = 72): Promise<WeatherTrendsResponse> {
    const query = encodeURIComponent(icaos.join(','))
    const res = await fetch(`${API_BASE}/api/visualizations/weather-trends?icaos=${query}&hours=${hours}`)
    if (!res.ok) throw new Error(`Weather trends error: ${res.statusText}`)
    const data = (await res.json()) as Partial<WeatherTrendsResponse>
    return {
      points: Array.isArray(data.points) ? data.points : [],
    }
  },

  async getFlightPaths(limit = 8): Promise<FlightPathsResponse> {
    const res = await fetch(`${API_BASE}/api/visualizations/flight-paths?limit=${limit}`)
    if (!res.ok) throw new Error(`Flight paths error: ${res.statusText}`)
    const data = (await res.json()) as Partial<FlightPathsResponse>
    return {
      nodes: Array.isArray(data.nodes) ? data.nodes : [],
      edges: Array.isArray(data.edges) ? data.edges : [],
    }
  },

  async getSafetyHeatmap(limit = 20): Promise<SafetyHeatmapResponse> {
    const res = await fetch(`${API_BASE}/api/visualizations/safety-heatmap?limit=${limit}`)
    if (!res.ok) throw new Error(`Safety heatmap error: ${res.statusText}`)
    const data = (await res.json()) as Partial<SafetyHeatmapResponse>
    return {
      cells: Array.isArray(data.cells) ? data.cells : [],
    }
  },
}

/**
 * Normalize response formats from different endpoints
 */
function normalizeResponse(data: AgentApiRawResponse): AgentResponse {
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
