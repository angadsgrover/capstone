import { useState } from 'react'
import { ChevronDown, ChevronRight, Brain, ListOrdered, Lightbulb, CheckCircle, Route, Sparkles, Clock, TrendingUp } from 'lucide-react'
import { Accordion, AccordionDetails, AccordionSummary, Box, Chip, Paper, Stack, Typography } from '@mui/material'
import { ThinkingStep } from '@/shared/types/agent'

interface ThinkingSectionProps {
  thinking?: ThinkingStep[]
  plan?: string[]
  route?: string
}

export default function ThinkingSection({ thinking, plan, route }: ThinkingSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  if ((!thinking || thinking.length === 0) && (!plan || plan.length === 0)) return null

  const hasContent = (thinking && thinking.length > 0) || (plan && plan.length > 0)
  if (!hasContent) return null

  // Calculate stats
  const thinkingCount = thinking?.length || 0
  const planCount = plan?.length || 0
  const complexity = thinkingCount + planCount > 5 ? 'high' : thinkingCount + planCount > 2 ? 'medium' : 'low'

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
          py: 0.5,
          bgcolor: 'action.hover',
          '& .MuiAccordionSummary-content': {
            alignItems: 'center',
            gap: 1,
            flexWrap: 'wrap',
          },
        }}
      >
        <Brain size={16} />
        <Typography fontWeight={700} fontSize={14}>
          Reasoning Process
        </Typography>
        {complexity !== 'low' && (
          <Chip
            size="small"
            color={complexity === 'high' ? 'error' : 'secondary'}
            icon={<TrendingUp size={14} />}
            label={`${complexity} complexity`}
          />
        )}
        {route && (
          <Chip size="small" variant="outlined" icon={<Route size={14} />} label={route.replace('_', ' ')} />
        )}
        {planCount > 0 && (
          <Chip size="small" icon={<ListOrdered size={14} />} label={`${planCount} planned`} />
        )}
        {thinkingCount > 0 && (
          <Chip size="small" icon={<Sparkles size={14} />} label={`${thinkingCount} thoughts`} />
        )}
      </AccordionSummary>

      <AccordionDetails sx={{ px: 2, pb: 2 }}>
        <Stack spacing={2}>
          {plan && plan.length > 0 && (
            <Paper variant="outlined" sx={{ p: 1.5 }}>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.25 }}>
                <ListOrdered size={16} />
                <Typography variant="subtitle2" fontWeight={700}>
                  Multi-Step Execution Plan
                </Typography>
              </Stack>
              <Stack component="ol" spacing={1.2} sx={{ m: 0, pl: 2.25 }}>
                {plan.map((step, idx) => (
                  <Box component="li" key={idx}>
                    <Typography variant="body2">{step}</Typography>
                  </Box>
                ))}
              </Stack>
            </Paper>
          )}

          {thinking && thinking.length > 0 && (
            <Stack spacing={1.2}>
              <Stack direction="row" spacing={1} alignItems="center">
                <Lightbulb size={16} />
                <Typography variant="subtitle2" fontWeight={700}>
                  Step-by-Step Reasoning
                </Typography>
              </Stack>

              {thinking.map((step, idx) => (
                <Paper key={idx} variant="outlined" sx={{ p: 1.5 }}>
                  <Stack spacing={0.8}>
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                      <Chip size="small" label={`${idx + 1}`} />
                      <Chip size="small" variant="outlined" label={step.type} />
                      <Stack direction="row" spacing={0.5} alignItems="center">
                        <Clock size={13} />
                        <Typography variant="caption" color="text.secondary">
                          {new Date(step.timestamp).toLocaleTimeString()}
                        </Typography>
                      </Stack>
                    </Stack>

                    <Typography variant="body2">{step.step}</Typography>

                    {step.result && (
                      <Paper variant="outlined" sx={{ p: 1.2, bgcolor: 'action.hover' }}>
                        <Stack direction="row" spacing={0.75} alignItems="center" sx={{ mb: 0.5 }}>
                          <CheckCircle size={14} />
                          <Typography variant="caption" fontWeight={700}>
                            Result
                          </Typography>
                        </Stack>
                        <Typography variant="body2" color="text.secondary">
                          {step.result}
                        </Typography>
                      </Paper>
                    )}
                  </Stack>
                </Paper>
              ))}
            </Stack>
          )}
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}
