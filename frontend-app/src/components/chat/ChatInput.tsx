import { useState, useRef, useCallback } from 'react'
import { Box, Button, Chip, CircularProgress, Paper, Stack, TextField, Typography } from '@mui/material'
import MaterialIcon from '@/components/ui/MaterialIcon'

interface ChatInputProps {
  onSend: (text: string) => void
  disabled?: boolean
  placeholder?: string
}

export default function ChatInput({ onSend, disabled, placeholder }: ChatInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

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

          <Button
            type="submit"
            variant="contained"
            disabled={disabled || !hasContent}
            sx={{ minWidth: { xs: '100%', sm: 130 }, height: 48 }}
            startIcon={disabled ? <CircularProgress size={16} color="inherit" /> : <MaterialIcon icon="send" filled={hasContent} />}
          >
            {disabled ? 'Processing' : 'Send'}
          </Button>
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
        </Stack>

        {value.length > 0 && (
          <Typography variant="caption" color="text.secondary">
            {value.length} chars
          </Typography>
        )}
      </Stack>
    </Box>
  )
}
