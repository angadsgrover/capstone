import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-lg border px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase transition-all duration-200',
  {
    variants: {
      variant: {
        default:
          'border-primary/30 bg-primary/12 text-primary',
        secondary:
          'border-secondary/30 bg-secondary/12 text-secondary',
        destructive:
          'border-error/30 bg-error/12 text-error',
        outline:
          'border-outline-variant/25 text-on-surface-variant',
        success:
          'border-[hsl(var(--status-vfr)/0.3)] bg-[hsl(var(--status-vfr)/0.12)] text-[hsl(var(--status-vfr))]',
        warning:
          'border-[hsl(var(--status-ifr)/0.3)] bg-[hsl(var(--status-ifr)/0.12)] text-[hsl(var(--status-ifr))]',
        info:
          'border-[hsl(var(--secondary)/0.3)] bg-[hsl(var(--secondary)/0.12)] text-secondary',
        purple:
          'border-tertiary/30 bg-tertiary/12 text-tertiary',
        live:
          'border-secondary/35 bg-secondary/15 text-secondary animate-pulse',
      },
      size: {
        default: 'px-2 py-0.5 text-[10px]',
        sm: 'px-1.5 py-0.5 text-[9px]',
        lg: 'px-3 py-1 text-xs',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, size, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant, size }), className)} {...props} />
}

export { Badge, badgeVariants }
