import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  alpha,
  Avatar,
  Box,
  Chip,
  Divider,
  IconButton,
  Paper,
  Stack,
  Tooltip,
  Typography,
  useTheme,
} from '@mui/material'
import MaterialIcon from '@/components/ui/MaterialIcon'
import { Message } from '@/shared/types/agent'
import ToolCallsSection from './ToolCallsSection'
import ThinkingSection from './ThinkingSection'
import LLMThinkingOutputSection from './LLMThinkingOutputSection'
import { useState } from 'react'

interface MessageBubbleProps {
  message: Message
  isStreaming?: boolean
}

export default function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const theme = useTheme()
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)
  const timestamp = new Date(message.timestamp)

  const copyToClipboard = async () => {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Stack direction="row" justifyContent={isUser ? 'flex-end' : 'flex-start'} sx={{ width: '100%' }}>
      <Stack
        direction={isUser ? 'row-reverse' : 'row'}
        spacing={1.5}
        sx={{ width: '100%', maxWidth: { xs: '95%', md: '78%' }, alignItems: 'flex-start' }}
      >
        <Avatar
          sx={{
            width: 40,
            height: 40,
            mt: 0.6,
            bgcolor: isUser ? 'primary.main' : alpha(theme.palette.secondary.main, 0.2),
            color: isUser ? 'primary.contrastText' : 'secondary.main',
          }}
        >
          <MaterialIcon icon={isUser ? 'person' : 'auto_awesome'} filled />
        </Avatar>

        <Stack spacing={0.8} sx={{ minWidth: 0, flex: 1 }}>
          <Stack
            direction="row"
            spacing={1}
            alignItems="center"
            justifyContent={isUser ? 'flex-end' : 'flex-start'}
            flexWrap="wrap"
            useFlexGap
          >
            <Typography variant="caption" fontWeight={700} color="text.secondary">
              {isUser ? 'You' : 'PolyU Weather AI'}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </Typography>
          </Stack>

          <Paper
            variant="outlined"
            sx={{
              position: 'relative',
              px: 2,
              py: 1.6,
              bgcolor: isUser ? 'primary.main' : alpha(theme.palette.background.paper, 0.82),
              color: isUser ? 'primary.contrastText' : 'text.primary',
              borderColor: isUser ? 'primary.main' : 'divider',
            }}
          >
            {isUser ? (
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.65 }}>
                {message.content}
              </Typography>
            ) : (
              <Box>
                {((message.thinking && message.thinking.length > 0) ||
                  (message.plan && message.plan.length > 0) ||
                  (message.toolCalls && message.toolCalls.length > 0)) && (
                  <Box sx={{ mb: 1.5 }}>
                    <ThinkingSection thinking={message.thinking} plan={message.plan} route={message.route} />
                    {message.thinking && message.thinking.length > 0 && (
                      <LLMThinkingOutputSection thinking={message.thinking} />
                    )}
                    {message.toolCalls && message.toolCalls.length > 0 && (
                      <ToolCallsSection toolCalls={message.toolCalls} />
                    )}

                    <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1.8 }}>
                      <Divider sx={{ flex: 1 }} />
                      <Chip size="small" icon={<MaterialIcon icon="check_circle" filled />} label="Final Output" />
                      <Divider sx={{ flex: 1 }} />
                    </Stack>
                  </Box>
                )}

                <Box sx={{
                  '& pre': {
                    margin: 0,
                  },
                  '& table': {
                    width: '100%',
                    borderCollapse: 'collapse',
                    fontSize: 13,
                  },
                  '& th, & td': {
                    borderBottom: `1px solid ${theme.palette.divider}`,
                    padding: '8px 10px',
                    textAlign: 'left',
                    verticalAlign: 'top',
                  },
                }}>
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      p: ({ ...props }) => <Typography sx={{ mb: 1.2, lineHeight: 1.72, '&:last-child': { mb: 0 } }} variant="body2" {...props} />,
                      ul: ({ ...props }) => <Box component="ul" sx={{ pl: 2.4, mb: 1.2 }} {...props} />,
                      ol: ({ ...props }) => <Box component="ol" sx={{ pl: 2.4, mb: 1.2 }} {...props} />,
                      li: ({ ...props }) => <Box component="li" sx={{ mb: 0.8 }} {...props} />,
                      h1: ({ ...props }) => <Typography variant="h6" sx={{ mt: 1.8, mb: 1 }} {...props} />,
                      h2: ({ ...props }) => <Typography variant="subtitle1" sx={{ mt: 1.6, mb: 0.9 }} {...props} />,
                      h3: ({ ...props }) => <Typography variant="subtitle2" sx={{ mt: 1.4, mb: 0.8 }} {...props} />,
                      blockquote: ({ children }) => (
                        <Paper
                          variant="outlined"
                          sx={{
                            my: 1.2,
                            px: 1.5,
                            py: 1,
                            borderLeftWidth: 3,
                            borderLeftColor: 'secondary.main',
                          }}
                        >
                          {children}
                        </Paper>
                      ),
                      a: ({ ...props }) => (
                        <Box
                          component="a"
                          target="_blank"
                          rel="noopener noreferrer"
                          sx={{ color: 'secondary.main', textDecorationColor: alpha(theme.palette.secondary.main, 0.4) }}
                          {...props}
                        />
                      ),
                      code: ({ className, children, ...props }: any) => {
                        const isBlock = /language-(\w+)/.test(className || '')
                        if (isBlock) {
                          const [, lang] = /language-(\w+)/.exec(className || '') || []
                          return (
                            <Paper variant="outlined" sx={{ my: 1.4, overflow: 'hidden' }}>
                              <Stack direction="row" justifyContent="space-between" sx={{ px: 1.2, py: 0.8, borderBottom: `1px solid ${theme.palette.divider}` }}>
                                <Typography variant="caption" fontWeight={700} color="text.secondary">
                                  {lang}
                                </Typography>
                                <IconButton size="small" onClick={() => navigator.clipboard.writeText(String(children))}>
                                  <MaterialIcon icon="content_copy" />
                                </IconButton>
                              </Stack>
                              <Box component="pre" sx={{ p: 1.2, overflowX: 'auto', fontSize: 13, lineHeight: 1.55, fontFamily: 'monospace' }}>
                                <code className={className}>{children}</code>
                              </Box>
                            </Paper>
                          )
                        }

                        return (
                          <Box
                            component="code"
                            sx={{
                              px: 0.65,
                              py: 0.2,
                              borderRadius: 1,
                              bgcolor: 'action.hover',
                              border: `1px solid ${theme.palette.divider}`,
                              fontSize: 13,
                              fontFamily: 'monospace',
                            }}
                            {...props}
                          >
                            {children}
                          </Box>
                        )
                      },
                      pre: ({ ...props }) => <Box component="pre" {...props} />,
                      strong: ({ ...props }) => <Box component="strong" sx={{ fontWeight: 700 }} {...props} />,
                    }}
                  >
                    {message.content}
                  </ReactMarkdown>
                </Box>

                {isStreaming && (
                  <Box
                    component="span"
                    sx={{
                      ml: 0.4,
                      display: 'inline-block',
                      width: 4,
                      height: 14,
                      borderRadius: 2,
                      bgcolor: 'secondary.main',
                      animation: 'pulse-subtle 1.2s ease-in-out infinite',
                    }}
                  />
                )}
              </Box>
            )}

            {!isUser && !isStreaming && message.content && (
              <Tooltip title={copied ? 'Copied' : 'Copy message'}>
                <IconButton
                  size="small"
                  onClick={copyToClipboard}
                  sx={{
                    position: 'absolute',
                    right: 8,
                    bottom: 8,
                    bgcolor: alpha(theme.palette.background.paper, 0.85),
                    border: `1px solid ${theme.palette.divider}`,
                    '&:hover': {
                      bgcolor: 'background.paper',
                    },
                  }}
                >
                  <MaterialIcon icon={copied ? 'check' : 'content_copy'} />
                </IconButton>
              </Tooltip>
            )}
          </Paper>
        </Stack>
      </Stack>
    </Stack>
  )
}
