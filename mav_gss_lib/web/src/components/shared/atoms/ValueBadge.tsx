import { Activity, AlertTriangle, CheckCircle, Circle, File, Reply, Send } from 'lucide-react'
import { labelTone, toneColor } from '@/lib/colors'

const semanticIconMap: Record<string, React.ElementType> = {
  command: Send,
  request: Send,
  response: Reply,
  ack: CheckCircle,
  telemetry: Activity,
  file: File,
  error: AlertTriangle,
  unknown: Circle,
}

export function ValueBadge({
  value,
  tone,
  iconToken,
}: {
  value: string | number
  tone?: string | null
  iconToken?: string
}) {
  const label = String(value)
  const Icon = iconToken ? semanticIconMap[iconToken] : null
  const toneKey = tone && tone in toneColor ? tone as keyof typeof toneColor : labelTone(label)
  const fg = toneColor[toneKey]
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0 rounded-sm border text-[11px] font-medium tracking-wide shrink-0"
      style={{ color: fg, borderColor: `${fg}40`, backgroundColor: `${fg}0A` }}
    >
      {Icon && <Icon className="size-2.5" />}
      {label}
    </span>
  )
}
