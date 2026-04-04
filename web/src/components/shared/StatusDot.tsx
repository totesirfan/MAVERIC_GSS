import { colors } from '@/lib/colors'

interface StatusDotProps {
  status: string
  label?: string
}

function dotColor(status: string): string {
  const upper = status.toUpperCase()
  if (upper === 'ONLINE' || upper === 'LIVE' || upper === 'BOUND') return colors.success
  if (upper === 'RETRY') return colors.warning
  return colors.error
}

export function StatusDot({ status, label }: StatusDotProps) {
  const color = dotColor(status)
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="inline-block size-2 rounded-full"
        style={{ backgroundColor: color, boxShadow: `0 0 6px ${color}` }}
      />
      <span className="text-xs" style={{ color }}>
        {label ?? status}
      </span>
    </span>
  )
}
