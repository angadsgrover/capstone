import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Room, RoomEvent, Track } from 'livekit-client'
import { livekitService } from '@/shared/services/livekitService'

type MicPermission = 'unknown' | 'granted' | 'denied'

interface SpeechRecognitionLike {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: Event) => void) | null
  onend: (() => void) | null
  onerror: ((event: Event) => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

interface SpeechRecognitionErrorLike extends Event {
  error?: string
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike

interface VoiceOptions {
  onTranscriptFinal: (text: string) => void
}

interface UseLiveKitVoiceResult {
  isConnected: boolean
  isConnecting: boolean
  isListening: boolean
  autoSpeakEnabled: boolean
  micPermission: MicPermission
  interimTranscript: string
  statusLabel: string
  toggleConnection: () => Promise<void>
  startVoiceInput: () => Promise<void>
  stopVoiceInput: () => void
  toggleAutoSpeak: () => void
  speakText: (text: string) => void
  stopSpeaking: () => void
}

const LIVEKIT_ROOM_NAME = import.meta.env.VITE_LIVEKIT_ROOM_NAME ?? 'polyu-weather-voice'

function speechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null
  const speechWindow = window as Window & {
    SpeechRecognition?: SpeechRecognitionCtor
    webkitSpeechRecognition?: SpeechRecognitionCtor
  }
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null
}

function parseRecognitionEvent(event: Event): { finalText: string; interimText: string } {
  const candidate = event as Event & {
    resultIndex?: number
    results?: ArrayLike<{ isFinal?: boolean; 0?: { transcript?: string } }>
  }

  const results = candidate.results
  const startIndex = candidate.resultIndex ?? 0
  if (!results) {
    return { finalText: '', interimText: '' }
  }

  let finalText = ''
  let interimText = ''
  for (let i = startIndex; i < results.length; i++) {
    const result = results[i]
    const transcript = result?.[0]?.transcript?.trim() ?? ''
    if (!transcript) continue
    if (result?.isFinal) {
      finalText += `${transcript} `
    } else {
      interimText += `${transcript} `
    }
  }

  return {
    finalText: finalText.trim(),
    interimText: interimText.trim(),
  }
}

function parseLiveKitSegments(value: unknown): Array<{ text: string; final: boolean }> {
  if (!Array.isArray(value)) return []

  return value
    .map((segment) => {
      if (!segment || typeof segment !== 'object') return null
      const candidate = segment as { text?: unknown; final?: unknown }
      if (typeof candidate.text !== 'string' || !candidate.text.trim()) return null
      return {
        text: candidate.text,
        final: Boolean(candidate.final),
      }
    })
    .filter((segment): segment is { text: string; final: boolean } => segment !== null)
}

function getMicrophoneApiUnavailableMessage(): string {
  if (typeof window !== 'undefined' && !window.isSecureContext) {
    return 'Microphone requires HTTPS or localhost. Open this app via a secure domain.'
  }

  return 'Microphone API is not available in this browser'
}

export function useLiveKitVoice({ onTranscriptFinal }: VoiceOptions): UseLiveKitVoiceResult {
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [autoSpeakEnabled, setAutoSpeakEnabled] = useState(import.meta.env.VITE_LIVEKIT_AUTO_SPEAK !== 'false')
  const [micPermission, setMicPermission] = useState<MicPermission>('unknown')
  const [interimTranscript, setInterimTranscript] = useState('')
  const [statusLabel, setStatusLabel] = useState('Voice offline')

  const roomRef = useRef<Room | null>(null)
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const attachedAudioRefs = useRef<HTMLMediaElement[]>([])
  const shouldKeepListeningRef = useRef(false)
  const restartTimerRef = useRef<number | null>(null)
  const restartAttemptsRef = useRef(0)
  const networkErrorCountRef = useRef(0)
  const livekitMicSuspendedForInputRef = useRef(false)
  
  // MediaRecorder fallback refs for browsers without Web Speech API
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const useFallbackRef = useRef(false)

  const speechSupported = useMemo(() => speechRecognitionCtor() !== null, [])

  const cleanupAudioElements = useCallback(() => {
    for (const element of attachedAudioRefs.current) {
      try {
        element.pause()
        element.srcObject = null
        element.remove()
      } catch {
        // Ignore cleanup errors from detached media elements.
      }
    }
    attachedAudioRefs.current = []
  }, [])

  const ensureMicrophoneAccess = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error(getMicrophoneApiUnavailableMessage())
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      setMicPermission('granted')
      stream.getTracks().forEach((track) => track.stop())
    } catch (error) {
      if (typeof DOMException !== 'undefined' && error instanceof DOMException) {
        if (error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError') {
          setMicPermission('denied')
          throw new Error('Microphone permission denied. Allow access in browser site settings.')
        }

        if (error.name === 'NotFoundError' || error.name === 'DevicesNotFoundError') {
          setMicPermission('unknown')
          throw new Error('No microphone detected. Connect a microphone and try again.')
        }

        if (error.name === 'NotReadableError' || error.name === 'TrackStartError') {
          setMicPermission('unknown')
          throw new Error('Microphone is busy in another app. Close other audio apps and retry.')
        }

        if (error.name === 'SecurityError') {
          setMicPermission('unknown')
          throw new Error(getMicrophoneApiUnavailableMessage())
        }
      }

      setMicPermission('unknown')
      const message = error instanceof Error ? error.message : 'Unable to access microphone'
      throw new Error(message)
    }
  }, [])

  const disconnectLiveKit = useCallback(async () => {
    const room = roomRef.current
    roomRef.current = null

    if (room) {
      try {
        await room.localParticipant.setMicrophoneEnabled(false)
      } catch {
        // Best effort only.
      }
      room.disconnect()
    }

    cleanupAudioElements()
    livekitMicSuspendedForInputRef.current = false
    setIsConnected(false)
    setStatusLabel('Voice offline')
  }, [cleanupAudioElements])

  const connectLiveKit = useCallback(async () => {
    if (roomRef.current) return

    setIsConnecting(true)
    setStatusLabel('Checking microphone...')

    try {
      await ensureMicrophoneAccess()

      const tokenResponse = await livekitService.fetchLiveKitToken({
        room_name: LIVEKIT_ROOM_NAME,
        participant_identity: `web-${Date.now().toString(36)}`,
        participant_name: 'PolyU Web User',
        participant_metadata: JSON.stringify({ source: 'frontend-chat' }),
      })

      const room = new Room()
      roomRef.current = room

      room.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind !== Track.Kind.Audio) return
        const audioElement = track.attach() as HTMLMediaElement
        audioElement.autoplay = true
        audioElement.style.display = 'none'
        document.body.appendChild(audioElement)
        attachedAudioRefs.current.push(audioElement)
      })

      room.on(RoomEvent.TranscriptionReceived, (segments) => {
        const parsedSegments = parseLiveKitSegments(segments)
        if (!parsedSegments.length) return

        const finalText = parsedSegments
          .filter((segment) => segment.final)
          .map((segment) => segment.text)
          .join(' ')
          .trim()
        const interimText = parsedSegments
          .filter((segment) => !segment.final)
          .map((segment) => segment.text)
          .join(' ')
          .trim()

        setInterimTranscript(interimText)
        if (finalText) {
          setInterimTranscript('')
          onTranscriptFinal(finalText)
        }
      })

      room.on(RoomEvent.Disconnected, () => {
        cleanupAudioElements()
        setIsConnected(false)
        setStatusLabel('Voice offline')
      })

      room.on(RoomEvent.ConnectionStateChanged, (state) => {
        setStatusLabel(`LiveKit ${String(state).toLowerCase()}`)
      })

      await room.connect(tokenResponse.server_url, tokenResponse.participant_token)
      await room.localParticipant.setMicrophoneEnabled(true)

      setIsConnected(true)
      setStatusLabel('LiveKit connected')
    } catch (error) {
      await disconnectLiveKit()
      const message = error instanceof Error ? error.message : 'Unable to connect voice session'
      setStatusLabel('Voice connection failed')
      throw new Error(message)
    } finally {
      setIsConnecting(false)
    }
  }, [cleanupAudioElements, disconnectLiveKit, ensureMicrophoneAccess, onTranscriptFinal])

  const toggleConnection = useCallback(async () => {
    if (isConnected || roomRef.current) {
      await disconnectLiveKit()
      return
    }
    await connectLiveKit()
  }, [connectLiveKit, disconnectLiveKit, isConnected])

  const restoreLiveKitMicAfterInput = useCallback(() => {
    if (!livekitMicSuspendedForInputRef.current) return

    const room = roomRef.current
    livekitMicSuspendedForInputRef.current = false
    if (!room) return

    void room.localParticipant.setMicrophoneEnabled(true).catch(() => {
      // Best effort restore only.
    })
  }, [])

  const suspendLiveKitMicForInput = useCallback(async () => {
    if (!isConnected) return

    const room = roomRef.current
    if (!room || livekitMicSuspendedForInputRef.current) return

    try {
      await room.localParticipant.setMicrophoneEnabled(false)
      livekitMicSuspendedForInputRef.current = true
    } catch {
      // Best effort only; speech recognition may still work depending on browser.
    }
  }, [isConnected])

  // MediaRecorder fallback for browsers without Web Speech API (Firefox, Safari, Brave)
  const startFallbackRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      mediaStreamRef.current = stream
      audioChunksRef.current = []

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm')
        ? 'audio/webm'
        : 'audio/mp4'

      const recorder = new MediaRecorder(stream, { mimeType })
      mediaRecorderRef.current = recorder

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data)
        }
      }

      recorder.onstop = async () => {
        // Clean up stream
        mediaStreamRef.current?.getTracks().forEach((track) => track.stop())
        mediaStreamRef.current = null

        if (audioChunksRef.current.length === 0) {
          setIsListening(false)
          setStatusLabel(roomRef.current ? 'LiveKit connected' : 'Voice ready')
          restoreLiveKitMicAfterInput()
          return
        }

        // Convert to base64 and transcribe
        setStatusLabel('Transcribing...')
        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType })
        audioChunksRef.current = []

        try {
          const arrayBuffer = await audioBlob.arrayBuffer()
          const base64 = btoa(
            new Uint8Array(arrayBuffer).reduce((data, byte) => data + String.fromCharCode(byte), '')
          )

          const result = await livekitService.transcribeAudio({
            audio_base64: base64,
            language: 'en',
          })

          if (result.text.trim()) {
            onTranscriptFinal(result.text.trim())
          }
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Transcription failed'
          setStatusLabel(message)
        }

        setIsListening(false)
        setStatusLabel(roomRef.current ? 'LiveKit connected' : 'Voice ready')
        restoreLiveKitMicAfterInput()
      }

      recorder.onerror = () => {
        setIsListening(false)
        setStatusLabel('Recording failed')
        mediaStreamRef.current?.getTracks().forEach((track) => track.stop())
        mediaStreamRef.current = null
        restoreLiveKitMicAfterInput()
      }

      await suspendLiveKitMicForInput()
      recorder.start()
      setIsListening(true)
      setStatusLabel('Recording... (release to transcribe)')
    } catch (error) {
      setIsListening(false)
      const message = error instanceof Error ? error.message : 'Failed to start recording'
      setStatusLabel(message)
      throw error
    }
  }, [onTranscriptFinal, restoreLiveKitMicAfterInput, suspendLiveKitMicForInput])

  const stopFallbackRecording = useCallback(() => {
    const recorder = mediaRecorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop()
    }
    mediaRecorderRef.current = null
  }, [])

  const stopVoiceInput = useCallback(() => {
    shouldKeepListeningRef.current = false
    restartAttemptsRef.current = 0
    setInterimTranscript('')

    if (restartTimerRef.current !== null) {
      window.clearTimeout(restartTimerRef.current)
      restartTimerRef.current = null
    }

    // Stop Web Speech API recognition
    const recognition = recognitionRef.current
    if (recognition) {
      try {
        recognition.stop()
      } catch {
        // Ignore transient stop errors.
      }
    }

    // Stop MediaRecorder fallback (this triggers transcription)
    if (useFallbackRef.current) {
      stopFallbackRecording()
      return // Don't reset state yet - onstop handler will do it after transcription
    }

    setIsListening(false)
    setStatusLabel(roomRef.current ? 'LiveKit connected' : 'Voice ready')
    restoreLiveKitMicAfterInput()
  }, [restoreLiveKitMicAfterInput, stopFallbackRecording])

  const startVoiceInput = useCallback(async () => {
    if (isListening) return

    if (micPermission !== 'granted') {
      try {
        await ensureMicrophoneAccess()
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Unable to access microphone'
        setStatusLabel(message)
        throw error
      }
    }

    // If Web Speech API is not supported or we're in fallback mode, use MediaRecorder
    if (!speechSupported || useFallbackRef.current) {
      useFallbackRef.current = true
      await startFallbackRecording()
      return
    }

    if (!recognitionRef.current) {
      const RecognitionCtor = speechRecognitionCtor()
      if (!RecognitionCtor) {
        // Fall back to MediaRecorder
        useFallbackRef.current = true
        await startFallbackRecording()
        return
      }

      const recognition = new RecognitionCtor()
      recognition.continuous = true
      recognition.interimResults = true
      recognition.lang = 'en-US'

      recognition.onresult = (event) => {
        // Reset network error count on successful result
        networkErrorCountRef.current = 0
        const { finalText, interimText } = parseRecognitionEvent(event)
        setInterimTranscript(interimText)
        if (finalText) {
          setInterimTranscript('')
          onTranscriptFinal(finalText)
        }
      }

      recognition.onend = () => {
        if (restartTimerRef.current !== null) {
          window.clearTimeout(restartTimerRef.current)
          restartTimerRef.current = null
        }

        if (shouldKeepListeningRef.current) {
          const scheduleRestart = (delayMs: number) => {
            restartTimerRef.current = window.setTimeout(() => {
              restartTimerRef.current = null
              if (!shouldKeepListeningRef.current) return

              try {
                recognition.start()
                restartAttemptsRef.current = 0
                setIsListening(true)
                setStatusLabel('Listening...')
              } catch {
                restartAttemptsRef.current += 1
                if (restartAttemptsRef.current < 8) {
                  // Retry transient start failures without dropping out of hold-to-speak.
                  scheduleRestart(Math.min(800, 120 + restartAttemptsRef.current * 80))
                  return
                }

                shouldKeepListeningRef.current = false
                restartAttemptsRef.current = 0
                setIsListening(false)
                setInterimTranscript('')
                setStatusLabel(roomRef.current ? 'LiveKit connected' : 'Voice ready')
              }
            }, delayMs)
          }

          restartTimerRef.current = window.setTimeout(() => {
            restartTimerRef.current = null
            if (!shouldKeepListeningRef.current) return

            try {
              recognition.start()
              restartAttemptsRef.current = 0
              setIsListening(true)
              setStatusLabel('Listening...')
            } catch {
              restartAttemptsRef.current += 1
              if (restartAttemptsRef.current < 8) {
                scheduleRestart(Math.min(800, 120 + restartAttemptsRef.current * 80))
                return
              }

              shouldKeepListeningRef.current = false
              restartAttemptsRef.current = 0
              setIsListening(false)
              setInterimTranscript('')
              setStatusLabel(roomRef.current ? 'LiveKit connected' : 'Voice ready')
            }
          }, 120)
          return
        }

        restartAttemptsRef.current = 0
        setIsListening(false)
        setInterimTranscript('')
        setStatusLabel(roomRef.current ? 'LiveKit connected' : 'Voice ready')
      }

      recognition.onerror = (event) => {
        const errorCode = (event as SpeechRecognitionErrorLike).error ?? ''

        // Ignore transient errors while push-to-talk is still active.
        // These errors don't mean recognition failed - onend will fire and handle restart.
        if (shouldKeepListeningRef.current && (errorCode === 'aborted' || errorCode === 'no-speech')) {
          return
        }

        // Audio-capture errors are often transient (mic busy with another app).
        // Allow auto-restart to recover instead of immediately giving up.
        if (shouldKeepListeningRef.current && errorCode === 'audio-capture') {
          // onend will fire and attempt restart
          setStatusLabel('Retrying mic access...')
          return
        }

        // Network errors from the speech recognition service are transient.
        // Allow limited auto-restart attempts before giving up.
        // Note: Brave and other privacy-focused browsers block Google's speech service.
        if (shouldKeepListeningRef.current && errorCode === 'network') {
          networkErrorCountRef.current += 1
          
          // After 3 network errors, switch to fallback mode
          if (networkErrorCountRef.current >= 3) {
            shouldKeepListeningRef.current = false
            networkErrorCountRef.current = 0
            restartAttemptsRef.current = 0
            setIsListening(false)
            setInterimTranscript('')
            restoreLiveKitMicAfterInput()
            
            // Enable fallback mode for future attempts
            useFallbackRef.current = true
            setStatusLabel('Switched to push-to-talk mode')
            return
          }
          
          // onend will fire and attempt restart
          setStatusLabel('Reconnecting speech service...')
          return
        }

        // For fatal errors, stop listening entirely.
        shouldKeepListeningRef.current = false
        restartAttemptsRef.current = 0
        setIsListening(false)
        setInterimTranscript('')
        restoreLiveKitMicAfterInput()

        if (errorCode === 'not-allowed' || errorCode === 'service-not-allowed') {
          setMicPermission('denied')
          setStatusLabel('Microphone blocked')
          return
        }

        if (errorCode === 'audio-capture') {
          setStatusLabel('Microphone busy')
          return
        }

        if (errorCode === 'network') {
          setStatusLabel('Speech service unavailable')
          return
        }

        setStatusLabel('Voice input stopped')
      }

      recognitionRef.current = recognition
    }

    try {
      shouldKeepListeningRef.current = true
      restartAttemptsRef.current = 0
      networkErrorCountRef.current = 0
      
      // Suspend LiveKit mic first (best-effort, won't throw)
      await suspendLiveKitMicForInput()
      
      // Start recognition BEFORE updating UI state to avoid flash
      recognitionRef.current.start()
      
      // Only update UI state after successful start
      setStatusLabel('Listening...')
      setIsListening(true)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to start voice input'

      // Ignore duplicate start attempts while recognition is already active.
      if (/invalidstateerror|already\s*started/i.test(message)) {
        shouldKeepListeningRef.current = true
        setIsListening(true)
        setStatusLabel('Listening...')
        return
      }

      shouldKeepListeningRef.current = false
      restartAttemptsRef.current = 0
      setIsListening(false)
      restoreLiveKitMicAfterInput()
      throw new Error(message)
    }
  }, [
    ensureMicrophoneAccess,
    isListening,
    micPermission,
    onTranscriptFinal,
    restoreLiveKitMicAfterInput,
    speechSupported,
    startFallbackRecording,
    suspendLiveKitMicForInput,
  ])

  const stopSpeaking = useCallback(() => {
    if (typeof window === 'undefined' || !window.speechSynthesis) return
    window.speechSynthesis.cancel()
  }, [])

  const speakText = useCallback((text: string) => {
    if (!autoSpeakEnabled) return
    if (typeof window === 'undefined' || !window.speechSynthesis) return

    const utterance = new SpeechSynthesisUtterance(text)
    utterance.rate = 1
    utterance.pitch = 1
    utterance.volume = 1

    window.speechSynthesis.cancel()
    window.speechSynthesis.speak(utterance)
  }, [autoSpeakEnabled])

  const toggleAutoSpeak = useCallback(() => {
    setAutoSpeakEnabled((current) => {
      if (current) {
        stopSpeaking()
      }
      return !current
    })
  }, [stopSpeaking])

  useEffect(() => {
    return () => {
      shouldKeepListeningRef.current = false
      restartAttemptsRef.current = 0
      if (restartTimerRef.current !== null) {
        window.clearTimeout(restartTimerRef.current)
        restartTimerRef.current = null
      }

      const recognition = recognitionRef.current
      recognitionRef.current = null
      if (recognition) {
        try {
          recognition.abort()
        } catch {
          // Ignore teardown errors.
        }
      }

      // Clean up MediaRecorder fallback
      const recorder = mediaRecorderRef.current
      mediaRecorderRef.current = null
      if (recorder && recorder.state !== 'inactive') {
        try {
          recorder.stop()
        } catch {
          // Ignore teardown errors.
        }
      }
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop())
      mediaStreamRef.current = null

      restoreLiveKitMicAfterInput()
      stopSpeaking()
      void disconnectLiveKit()
    }
  }, [disconnectLiveKit, restoreLiveKitMicAfterInput, stopSpeaking])

  return {
    isConnected,
    isConnecting,
    isListening,
    autoSpeakEnabled,
    micPermission,
    interimTranscript,
    statusLabel,
    toggleConnection,
    startVoiceInput,
    stopVoiceInput,
    toggleAutoSpeak,
    speakText,
    stopSpeaking,
  }
}
