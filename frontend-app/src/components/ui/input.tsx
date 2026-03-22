import * as React from 'react'
import { cn } from '@/lib/utils'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, type, ...props }, ref) => (
  <input
    type={type}
    className={cn(
      'flex h-10 w-full rounded-xl border px-4 py-2 text-sm transition-all duration-200',
      'border-outline-variant/20 bg-surface-container-highest/70 text-on-surface placeholder:text-on-surface-variant/45',
      'hover:border-outline-variant/40',
      'focus:outline-none focus:ring-2 focus:ring-secondary/25 focus:border-secondary/50',
      'disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-surface-container',
      className,
    )}
    ref={ref}
    {...props}
  />
))
Input.displayName = 'Input'

export { Input }
