import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-lg border px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase transition-all duration-200',
  {
    variants: {
      variant: {
        default:
          'border-indigo-500/20 bg-indigo-500/10 text-indigo-600 dark:text-indigo-300',
        secondary:
          'border-slate-500/20 bg-slate-500/10 text-slate-600 dark:text-slate-300',
        destructive:
          'border-red-500/20 bg-red-500/10 text-red-600 dark:text-red-300',
        outline:
          'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300',
        success:
          'border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300',
        warning:
          'border-amber-500/20 bg-amber-500/10 text-amber-600 dark:text-amber-300',
        info:
          'border-blue-500/20 bg-blue-500/10 text-blue-600 dark:text-blue-300',
        purple:
          'border-purple-500/20 bg-purple-500/10 text-purple-600 dark:text-purple-300',
        live:
          'border-emerald-500/30 bg-emerald-500/15 text-emerald-600 dark:text-emerald-300 animate-pulse',
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
