import { useState } from 'react'
import { ChevronDown, ChevronRight, Wrench, CheckCircle, AlertCircle, Loader2, RotateCcw, Clock, Zap } from 'lucide-react'
import { Accordion, AccordionDetails, AccordionSummary, Box, Chip, Paper, Stack, Typography } from '@mui/material'
import { ToolCall } from '@/shared/types/agent'

interface ToolCallsSectionProps {
  toolCalls: ToolCall[]
}

export default function ToolCallsSection({ toolCalls }: ToolCallsSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!toolCalls || toolCalls.length === 0) return null

  const successCount = toolCalls.filter((t) => t.status === 'success').length
  const errorCount = toolCalls.filter((t) => t.status === 'error').length
  const runningCount = toolCalls.filter((t) => t.status === 'running').length
  const totalDuration = toolCalls.reduce((sum, t) => sum + (t.duration || 0), 0)

  return (
    <Accordion
      expanded={isExpanded}
      onChange={(_, expanded) => setIsExpanded(expanded)}
      disableGutters
      sx={{
        mt: 2,
        border: (theme) => `1px solid ${theme.palette.divider}`,
        borderRadius: 2,
        overflow: 'hidden',
        '&::before': { display: 'none' },
      }}
    >
      <AccordionSummary
        expandIcon={isExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
        sx={{
          px: 2,
          bgcolor: 'action.hover',
          '& .MuiAccordionSummary-content': {
            alignItems: 'center',
            gap: 1,
            flexWrap: 'wrap',
          },
        }}
      >
        <Wrench size={16} />
        <Typography variant="subtitle2" fontWeight={700}>
          Tools Executed
        </Typography>
        <Chip size="small" label={`${toolCalls.length}`} />

        {totalDuration > 0 && <Chip size="small" icon={<Zap size={14} />} label={`${totalDuration}ms`} />}
        {runningCount > 0 && <Chip size="small" color="primary" icon={<Loader2 size={14} />} label={`${runningCount} running`} />}
        {successCount > 0 && <Chip size="small" color="success" icon={<CheckCircle size={14} />} label={`${successCount} ok`} />}
        {errorCount > 0 && <Chip size="small" color="error" icon={<AlertCircle size={14} />} label={`${errorCount} errors`} />}
      </AccordionSummary>

      <AccordionDetails sx={{ px: 2, pb: 2 }}>
        <Stack spacing={1.2}>
          {toolCalls.map((tool, idx) => (
            <ToolCallItem key={idx} tool={tool} index={idx} />
          ))}
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}

function ToolCallItem({ tool, index }: { tool: ToolCall; index: number }) {
  const [showDetails, setShowDetails] = useState(false)

  const statusConfig = {
    running: {
      icon: <Loader2 size={14} />,
      chipColor: 'primary' as const,
    },
    success: {
      icon: <CheckCircle size={14} />,
      chipColor: 'success' as const,
    },
    error: {
      icon: <AlertCircle size={14} />,
      chipColor: 'error' as const,
    },
  }

  const status = tool.status ? (statusConfig[tool.status] || statusConfig.success) : statusConfig.success

  return (
    <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
      <Box
        role="button"
        onClick={() => setShowDetails(!showDetails)}
        sx={{
          px: 1.5,
          py: 1.3,
          cursor: 'pointer',
          display: 'flex',
          gap: 1,
          alignItems: 'center',
          '&:hover': { bgcolor: 'action.hover' },
        }}
      >
        <Chip size="small" label={index + 1} />
        <Chip size="small" color={status.chipColor} icon={status.icon} label={tool.status ?? 'success'} />
        <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 600, flex: 1 }} noWrap>
          {tool.name}
        </Typography>

        {tool.retries && tool.retries > 0 && (
          <Chip size="small" icon={<RotateCcw size={12} />} label={`${tool.retries} retry`} />
        )}

        {tool.duration !== undefined && (
          <Chip size="small" icon={<Zap size={12} />} label={`${tool.duration}ms`} />
        )}

        <ChevronDown size={16} style={{ transform: showDetails ? 'rotate(180deg)' : 'none', transition: 'transform 150ms ease' }} />
      </Box>

      {showDetails && (
        <Stack spacing={1.2} sx={{ px: 1.5, pb: 1.5, pt: 0.4, borderTop: (theme) => `1px solid ${theme.palette.divider}` }}>
          <Box>
            <Typography variant="caption" fontWeight={700} color="text.secondary">
              Input
            </Typography>
            <Paper variant="outlined" sx={{ mt: 0.5, p: 1, bgcolor: 'action.hover' }}>
              <Typography component="pre" variant="caption" sx={{ m: 0, whiteSpace: 'pre-wrap', overflowX: 'auto', fontFamily: 'monospace' }}>
                {JSON.stringify(tool.input, null, 2)}
              </Typography>
            </Paper>
          </Box>

          {tool.output && (
            <Box>
              <Typography variant="caption" fontWeight={700} color="success.main">
                Output
              </Typography>
              <Paper variant="outlined" sx={{ mt: 0.5, p: 1, bgcolor: 'action.hover', maxHeight: 180, overflow: 'auto' }}>
                <Typography component="pre" variant="caption" sx={{ m: 0, whiteSpace: 'pre-wrap', overflowX: 'auto', fontFamily: 'monospace' }}>
                  {typeof tool.output === 'string' ? tool.output : JSON.stringify(tool.output, null, 2)}
                </Typography>
              </Paper>
            </Box>
          )}

          {tool.error && (
            <Box>
              <Typography variant="caption" fontWeight={700} color="error.main">
                Error
              </Typography>
              <Paper variant="outlined" sx={{ mt: 0.5, p: 1, bgcolor: 'error.50' }}>
                <Typography component="pre" variant="caption" sx={{ m: 0, whiteSpace: 'pre-wrap', overflowX: 'auto', fontFamily: 'monospace' }}>
                  {tool.error}
                </Typography>
              </Paper>
            </Box>
          )}

          {tool.startTime && (
            <Stack direction="row" spacing={0.7} alignItems="center">
              <Clock size={13} />
              <Typography variant="caption" color="text.secondary">
                Started: {new Date(tool.startTime).toLocaleTimeString()}
                {tool.endTime ? ` -> Ended: ${new Date(tool.endTime).toLocaleTimeString()}` : ''}
              </Typography>
            </Stack>
          )}
        </Stack>
      )}
    </Paper>
  )
}
