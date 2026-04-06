const API_BASE = import.meta.env.VITE_AGENT_API_URL
  ?? (import.meta.env.DEV ? 'http://localhost:8000' : window.location.origin)

const LIVEKIT_TOKEN_ENDPOINT = import.meta.env.VITE_LIVEKIT_TOKEN_ENDPOINT ?? '/api/livekit/token'
const TRANSCRIBE_ENDPOINT = '/api/transcribe'
const TTS_ENDPOINT = '/api/tts'

export interface LiveKitTokenRequest {
  room_name?: string
  participant_identity?: string
  participant_name?: string
  participant_metadata?: string
  participant_attributes?: Record<string, string>
  room_config?: Record<string, unknown>
}

export interface LiveKitTokenResponse {
  server_url: string
  participant_token: string
  room_name?: string
  participant_identity?: string
  ttl_seconds?: number
}

export interface TranscribeRequest {
  audio_base64: string
  language?: string
}

export interface TranscribeResponse {
  text: string
  language: string
}

export interface NeuralTtsRequest {
  text: string
  voice?: string
  language?: string
  format?: 'mp3' | 'wav' | 'opus' | 'aac' | 'flac' | 'pcm'
  speed?: number
  model?: string
}

function resolveTokenUrl(): string {
  if (/^https?:\/\//i.test(LIVEKIT_TOKEN_ENDPOINT)) {
    return LIVEKIT_TOKEN_ENDPOINT
  }

  const normalizedPath = LIVEKIT_TOKEN_ENDPOINT.startsWith('/')
    ? LIVEKIT_TOKEN_ENDPOINT
    : `/${LIVEKIT_TOKEN_ENDPOINT}`
  return `${API_BASE}${normalizedPath}`
}

async function fetchLiveKitToken(payload: LiveKitTokenRequest): Promise<LiveKitTokenResponse> {
  const response = await fetch(resolveTokenUrl(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>
  if (!response.ok) {
    const details = typeof data.details === 'string' ? data.details : response.statusText
    throw new Error(`LiveKit token error: ${details || 'request failed'}`)
  }

  const serverUrl = typeof data.server_url === 'string' ? data.server_url : ''
  const participantToken = typeof data.participant_token === 'string' ? data.participant_token : ''
  if (!serverUrl || !participantToken) {
    throw new Error('LiveKit token endpoint returned invalid payload')
  }

  return {
    server_url: serverUrl,
    participant_token: participantToken,
    room_name: typeof data.room_name === 'string' ? data.room_name : undefined,
    participant_identity: typeof data.participant_identity === 'string' ? data.participant_identity : undefined,
    ttl_seconds: typeof data.ttl_seconds === 'number' ? data.ttl_seconds : undefined,
  }
}

async function transcribeAudio(payload: TranscribeRequest): Promise<TranscribeResponse> {
  const response = await fetch(`${API_BASE}${TRANSCRIBE_ENDPOINT}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>
  if (!response.ok) {
    const details = typeof data.details === 'string' ? data.details : (typeof data.error === 'string' ? data.error : response.statusText)
    throw new Error(`Transcription error: ${details || 'request failed'}`)
  }

  const text = typeof data.text === 'string' ? data.text : ''
  const language = typeof data.language === 'string' ? data.language : 'en'

  return { text, language }
}

async function synthesizeSpeech(payload: NeuralTtsRequest, signal?: AbortSignal): Promise<Blob> {
  const response = await fetch(`${API_BASE}${TTS_ENDPOINT}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })

  if (!response.ok) {
    const data = (await response.json().catch(() => ({}))) as Record<string, unknown>
    const details = typeof data.details === 'string'
      ? data.details
      : (typeof data.error === 'string' ? data.error : response.statusText)
    throw new Error(`Neural TTS error: ${details || 'request failed'}`)
  }

  const audioBlob = await response.blob()
  if (!audioBlob.size) {
    throw new Error('Neural TTS returned empty audio')
  }
  return audioBlob
}

export const livekitService = {
  fetchLiveKitToken,
  transcribeAudio,
  synthesizeSpeech,
}
