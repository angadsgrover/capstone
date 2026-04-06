/// <reference types="vite/client" />

interface ImportMetaEnv {
	readonly VITE_AGENT_API_URL?: string
	readonly VITE_ENABLE_STREAMING?: 'true' | 'false'
	readonly VITE_LIVEKIT_TOKEN_ENDPOINT?: string
	readonly VITE_LIVEKIT_ROOM_NAME?: string
	readonly VITE_LIVEKIT_AUTO_SPEAK?: 'true' | 'false'
	readonly VITE_TTS_VOICE_NAME?: string
	readonly VITE_TTS_LANG?: string
	readonly VITE_TTS_RATE?: string
	readonly VITE_TTS_PITCH?: string
	readonly VITE_TTS_VOLUME?: string
	readonly VITE_NEURAL_TTS_ENABLED?: 'true' | 'false'
	readonly VITE_NEURAL_TTS_PREFER?: 'true' | 'false'
	readonly VITE_NEURAL_TTS_MODEL?: string
	readonly VITE_NEURAL_TTS_VOICE?: string
	readonly VITE_NEURAL_TTS_FORMAT?: 'mp3' | 'wav' | 'opus' | 'aac' | 'flac' | 'pcm'
	readonly VITE_LANGCHAIN_ENABLED?: 'true' | 'false'
	readonly VITE_LANGCHAIN_BASE_URL?: string
	readonly VITE_LANGCHAIN_RUN_ENDPOINT?: string
	readonly VITE_LANGCHAIN_ASSISTANT_ID?: string
	readonly VITE_LANGCHAIN_API_KEY?: string
}

interface ImportMeta {
	readonly env: ImportMetaEnv
}
