import { cn } from '@/lib/utils'

interface MaterialIconProps {
  icon: string
  className?: string
  filled?: boolean
  onClick?: () => void
}

export default function MaterialIcon({ icon, className, filled = false, onClick }: MaterialIconProps) {
  return (
    <span
      className={cn(
        'material-symbols-outlined select-none',
        filled && 'filled',
        onClick && 'cursor-pointer',
        className
      )}
      onClick={onClick}
      aria-hidden="true"
    >
      {icon}
    </span>
  )
}
