import { colors } from '@/lib/colors'

interface StatusDotProps {
  status: string
  label?: string
}

function dotColor(status: string): string {
  const upper = status.toUpperCase()
  if (upper === 'ONLINE' || upper === 'LIVE' || upper === 'BOUND') return colors.success
  if (upper === 'RETRY') return colors.warning
  if (upper === 'REPLAY') return colors.warning
  return colors.danger
}

/** Shape indicator visible even in monochrome: ● LIVE, ▲ RETRY, ▶ REPLAY, ✕ DOWN */
function dotShape(status: string): string {
  const upper = status.toUpperCase()
  if (upper === 'ONLINE' || upper === 'LIVE' || upper === 'BOUND') return '\u25CF'
  if (upper === 'RETRY') return '\u25B2'
  if (upper === 'REPLAY') return '\u25B6'
  return '\u2715'
}

export function StatusDot({ status, label }: StatusDotProps) {
  const displayLabel = status === 'ONLINE' ? 'LIVE' : status
  const color = dotColor(status)
  const shape = dotShape(status)
  return (
    <span className="inline-flex items-center gap-1.5 color-transition">
      <span className="text-[11px] leading-none" style={{ color }}>{shape}</span>
      <span className="text-[11px] font-medium" style={{ color }}>{label ?? displayLabel}</span>
    </span>
  )
}
