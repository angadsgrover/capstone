import { useState } from 'react'
import { ChevronDown, ChevronRight, Sparkles, Brain, CheckCircle, ListOrdered, Clock } from 'lucide-react'
import { Accordion, AccordionDetails, AccordionSummary, Box, Chip, Paper, Stack, Typography } from '@mui/material'
import { ThinkingStep } from '@/shared/types/agent'

interface LLMThinkingOutputSectionProps {
  thinking: ThinkingStep[]
}

export default function LLMThinkingOutputSection({ thinking }: LLMThinkingOutputSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!thinking || thinking.length === 0) return null

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
          },
        }}
      >
        <Sparkles size={16} />
        <Typography variant="subtitle2" fontWeight={700}>
          LLM Thinking Output
        </Typography>
        <Chip size="small" label={`${thinking.length}`} />
      </AccordionSummary>

      <AccordionDetails sx={{ px: 2, pb: 2 }}>
        <Stack spacing={1.2}>
          {thinking.map((step, idx) => {
            const typeLabel = step.type === 'plan'
              ? 'plan'
              : step.type === 'synthesis'
                ? 'synthesis'
                : 'reasoning'

            return (
              <Paper key={`${idx}-${step.type}-${step.step.slice(0, 24)}`} variant="outlined" sx={{ p: 1.5 }}>
                <Stack spacing={0.8}>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Chip size="small" label={`${idx + 1}`} />
                    <Chip
                      size="small"
                      variant="outlined"
                      icon={
                        typeLabel === 'plan'
                          ? <ListOrdered size={14} />
                          : typeLabel === 'reasoning'
                            ? <Brain size={14} />
                            : <CheckCircle size={14} />
                      }
                      label={typeLabel}
                    />
                    <Stack direction="row" spacing={0.5} alignItems="center">
                      <Clock size={13} />
                      <Typography variant="caption" color="text.secondary">
                        {new Date(step.timestamp).toLocaleTimeString()}
                      </Typography>
                    </Stack>
                  </Stack>

                  <Typography variant="body2">{step.step}</Typography>

                  {step.result && (
                    <Box sx={{ p: 1, borderRadius: 1.5, bgcolor: 'action.hover' }}>
                      <Typography variant="body2" color="text.secondary">
                        {step.result}
                      </Typography>
                    </Box>
                  )}
                </Stack>
              </Paper>
            )
          })}
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}
