/// <reference types="vite/client" />

interface ImportMetaEnv {
	readonly VITE_AGENT_API_URL?: string
	readonly VITE_ENABLE_STREAMING?: 'true' | 'false'
	readonly VITE_LANGCHAIN_ENABLED?: 'true' | 'false'
	readonly VITE_LANGCHAIN_BASE_URL?: string
	readonly VITE_LANGCHAIN_RUN_ENDPOINT?: string
	readonly VITE_LANGCHAIN_ASSISTANT_ID?: string
	readonly VITE_LANGCHAIN_API_KEY?: string
}

interface ImportMeta {
	readonly env: ImportMetaEnv
}
