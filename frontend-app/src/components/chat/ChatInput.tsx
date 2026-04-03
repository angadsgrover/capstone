import { useState, useRef, useCallback, useEffect } from 'react'
import { Box, Button, Chip, CircularProgress, IconButton, Paper, Stack, TextField, Tooltip, Typography } from '@mui/material'
import MaterialIcon from '@/components/ui/MaterialIcon'

interface ChatInputProps {
  onSend: (text: string) => void
  onAbort?: () => void
  disabled?: boolean
  isProcessing?: boolean
  placeholder?: string
  onToggleVoiceConnection?: () => void
  onStartVoiceHold?: () => void
  onStopVoiceHold?: () => void
  onToggleAutoSpeak?: () => void
  voiceConnected?: boolean
  voiceConnecting?: boolean
  voiceListening?: boolean
  autoSpeakEnabled?: boolean
  voiceStatusLabel?: string
  voiceInterimTranscript?: string
  micPermission?: 'unknown' | 'granted' | 'denied'
  voiceDraftText?: string
  voiceDraftVersion?: number
}

export default function ChatInput({
  onSend,
  onAbort,
  disabled,
  isProcessing,
  placeholder,
  onToggleVoiceConnection,
  onStartVoiceHold,
  onStopVoiceHold,
  onToggleAutoSpeak,
  voiceConnected,
  voiceConnecting,
  voiceListening,
  autoSpeakEnabled,
  voiceStatusLabel,
  voiceInterimTranscript,
  micPermission,
  voiceDraftText,
  voiceDraftVersion,
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const lastAppliedVoiceVersionRef = useRef<number>(-1)
  const toggleVoiceInput = useCallback(() => {
    if (voiceListening) {
      onStopVoiceHold?.()
      return
    }
    onStartVoiceHold?.()
  }, [onStartVoiceHold, onStopVoiceHold, voiceListening])

  useEffect(() => {
    if (typeof voiceDraftVersion !== 'number' || !voiceDraftText?.trim()) return
    if (voiceDraftVersion === lastAppliedVoiceVersionRef.current) return

    lastAppliedVoiceVersionRef.current = voiceDraftVersion
    setValue((prev) => {
      const current = prev.trim()
      return current ? `${current} ${voiceDraftText.trim()}` : voiceDraftText.trim()
    })
    textareaRef.current?.focus()
  }, [voiceDraftText, voiceDraftVersion])

  const submit = useCallback(() => {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setValue('')
  }, [value, disabled, onSend])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const hasContent = value.trim().length > 0
  const hasVoiceControls = Boolean(onToggleVoiceConnection || onStartVoiceHold || onToggleAutoSpeak)

  return (
    <Box>
      <Paper
        component="form"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
        elevation={0}
        sx={{
          p: 1.5,
          border: (theme) => `1px solid ${theme.palette.divider}`,
          backdropFilter: 'blur(8px)',
        }}
      >
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25} alignItems={{ sm: 'flex-end' }}>
          <TextField
            inputRef={textareaRef}
            fullWidth
            multiline
            minRows={1}
            maxRows={6}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            placeholder={placeholder ?? 'Ask about aviation weather...'}
            autoFocus
            variant="outlined"
          />

          {hasVoiceControls && (
            <Stack direction="row" spacing={0.6} alignItems="center" sx={{ alignSelf: { xs: 'stretch', sm: 'center' } }}>
              {onToggleVoiceConnection && (
                <Tooltip title={voiceConnected ? 'Disconnect LiveKit voice' : 'Connect LiveKit voice'}>
                  <span>
                    <IconButton
                      onClick={onToggleVoiceConnection}
                      disabled={disabled || Boolean(voiceConnecting)}
                      color={voiceConnected ? 'success' : 'default'}
                    >
                      <MaterialIcon icon={voiceConnected ? 'link_off' : 'link'} filled={voiceConnected} />
                    </IconButton>
                  </span>
                </Tooltip>
              )}

              {onStartVoiceHold && (
                <Tooltip title={voiceListening ? 'Stop voice input' : 'Start voice input'}>
                  <span>
                    <IconButton
                      disabled={disabled || Boolean(voiceConnecting)}
                      color={voiceListening ? 'secondary' : 'default'}
                      onClick={(event) => {
                        event.preventDefault()
                        toggleVoiceInput()
                      }}
                    >
                      <MaterialIcon icon={voiceListening ? 'mic_off' : 'mic'} filled={voiceListening} />
                    </IconButton>
                  </span>
                </Tooltip>
              )}

              {onToggleAutoSpeak && (
                <Tooltip title={autoSpeakEnabled ? 'Disable spoken responses' : 'Enable spoken responses'}>
                  <span>
                    <IconButton onClick={onToggleAutoSpeak} disabled={disabled} color={autoSpeakEnabled ? 'primary' : 'default'}>
                      <MaterialIcon icon={autoSpeakEnabled ? 'volume_up' : 'volume_off'} filled={autoSpeakEnabled} />
                    </IconButton>
                  </span>
                </Tooltip>
              )}
            </Stack>
          )}

          {isProcessing && onAbort ? (
            <Button
              type="button"
              variant="outlined"
              color="error"
              onClick={onAbort}
              sx={{ minWidth: { xs: '100%', sm: 130 }, height: 48 }}
              startIcon={<MaterialIcon icon="stop_circle" filled />}
            >
              Stop
            </Button>
          ) : (
            <Button
              type="submit"
              variant="contained"
              disabled={disabled || !hasContent}
              sx={{ minWidth: { xs: '100%', sm: 130 }, height: 48 }}
              startIcon={disabled ? <CircularProgress size={16} color="inherit" /> : <MaterialIcon icon="send" filled={hasContent} />}
            >
              {disabled ? 'Processing' : 'Send'}
            </Button>
          )}
        </Stack>
      </Paper>

      <Stack
        direction={{ xs: 'column', sm: 'row' }}
        justifyContent="space-between"
        alignItems={{ sm: 'center' }}
        spacing={1}
        sx={{ pt: 1.2, px: 0.5 }}
      >
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Chip size="small" variant="outlined" label="Enter to send" />
          <Chip size="small" variant="outlined" label="Shift+Enter new line" />
          {hasVoiceControls && voiceStatusLabel && (
            <Chip
              size="small"
              variant="outlined"
              color={voiceConnected ? 'success' : 'default'}
              label={voiceStatusLabel}
            />
          )}
          {hasVoiceControls && micPermission === 'denied' && (
            <Chip size="small" color="error" variant="outlined" label="Mic blocked" />
          )}
        </Stack>

        <Stack direction="column" spacing={0.25} alignItems={{ xs: 'flex-start', sm: 'flex-end' }}>
          {voiceInterimTranscript && (
            <Typography variant="caption" color="secondary.main" sx={{ maxWidth: 300 }}>
              Listening: {voiceInterimTranscript}
            </Typography>
          )}
          {value.length > 0 && (
            <Typography variant="caption" color="text.secondary">
              {value.length} chars
            </Typography>
          )}
        </Stack>
      </Stack>
    </Box>
  )
}
