export interface ExecutionTraceStepData {
  step: number
  task: string
  result: string | Record<string, unknown>
}

export interface AgentApiRawResponse {
  response?: string
  status?: 'success' | 'error'
  data?: Record<string, unknown>
  final_response?: string
  result?: unknown
  output?: string
  route?: string
  plan?: string[]
  execution_trace?: ExecutionTraceStepData[]
  multi_step?: boolean
  [key: string]: unknown
}

export interface AirportPoint {
  icao: string
  lat: number
  lon: number
  obs_time?: string
  flight_cat?: string
  temp_c?: number
  wind_speed_kt?: number
}

export interface AirportMapResponse {
  airports: AirportPoint[]
}

export interface TrendPoint {
  icao: string
  obs_time?: string
  wind_speed_kt?: number
  temp_c?: number
}

export interface WeatherTrendsResponse {
  points: TrendPoint[]
}

export interface HeatCell {
  icao: string
  incidents: number
  severity_score: number
}

export interface SafetyHeatmapResponse {
  cells: HeatCell[]
}

export interface FlightPathNode {
  id: string
  label?: string
  lat?: number
  lon?: number
}

export interface FlightPathEdge {
  id: string
  source: string
  target: string
}

export interface FlightPathsResponse {
  nodes: FlightPathNode[]
  edges: FlightPathEdge[]
}

export interface StreamPayload {
  chunk?: string
  data?: string
  tool_start?: string
  tool_end?: string
  tool_input?: Record<string, unknown>
  input?: Record<string, unknown>
  name?: string
  output?: string
  result?: string
  error?: string
  duration?: number
  type?: 'plan' | 'reasoning' | 'synthesis'
  thinking?: string
  step?: string
  plan?: string[]
  steps?: string[]
  route?: string
  specialist?: string
}
