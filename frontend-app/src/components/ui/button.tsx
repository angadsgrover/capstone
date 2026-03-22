import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 active:scale-[0.98]',
  {
    variants: {
      variant: {
        default:
          'user-gradient text-on-primary-container shadow-lg shadow-primary/20 hover:shadow-xl hover:shadow-primary/30 hover:brightness-110',
        destructive:
          'bg-[hsl(var(--error-container))] text-[hsl(var(--on-error-container))] shadow-lg shadow-[hsl(var(--error)/0.2)] hover:brightness-110',
        outline:
          'border border-outline-variant/20 bg-surface-container-high/70 backdrop-blur-sm text-on-surface hover:bg-surface-container-highest hover:border-secondary/30',
        secondary:
          'bg-secondary/12 text-secondary border border-secondary/30 hover:bg-secondary/20 hover:shadow-glow-secondary',
        ghost:
          'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface',
        link:
          'text-secondary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-10 px-5 py-2',
        sm: 'h-8 px-3.5 text-xs',
        lg: 'h-12 px-8 text-base',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button ref={ref} className={cn(buttonVariants({ variant, size, className }))} {...props} />
  ),
)
Button.displayName = 'Button'

export { Button, buttonVariants }
