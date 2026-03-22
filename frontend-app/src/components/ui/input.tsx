import * as React from 'react'
import { cn } from '@/lib/utils'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, type, ...props }, ref) => (
  <input
    type={type}
    className={cn(
      // Base
      'flex h-10 w-full rounded-xl border px-4 py-2 text-sm transition-all duration-200',
      // Light mode
      'border-slate-200 bg-white text-slate-900 placeholder:text-slate-400',
      'hover:border-slate-300',
      'focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500',
      // Dark mode
      'dark:border-slate-700 dark:bg-slate-800/50 dark:text-white dark:placeholder:text-slate-500',
      'dark:hover:border-slate-600',
      'dark:focus:ring-indigo-500/30 dark:focus:border-indigo-500',
      // Disabled
      'disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-slate-100 dark:disabled:bg-slate-800',
      className,
    )}
    ref={ref}
    {...props}
  />
))
Input.displayName = 'Input'

export { Input }
