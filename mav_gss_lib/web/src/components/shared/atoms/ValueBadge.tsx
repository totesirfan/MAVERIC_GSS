import { Activity, CheckCircle, Circle, File, Reply, Send } from 'lucide-react'
import { labelTone, toneColor } from '@/lib/colors'

const iconMap: Record<string, React.ElementType> = {
  CMD: Send,
  REQ: Send,
  RES: Reply,
  ACK: CheckCircle,
  TLM: Activity,
  FILE: File,
}

export function ValueBadge({ value, tone }: { value: string | number; tone?: string | null }) {
  const label = String(value)
  const Icon = iconMap[label.toUpperCase()] ?? Circle
  const toneKey = tone && tone in toneColor ? tone as keyof typeof toneColor : labelTone(label)
  const fg = toneColor[toneKey]
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0 rounded-sm border text-[11px] font-medium tracking-wide shrink-0"
      style={{ color: fg, borderColor: `${fg}40`, backgroundColor: `${fg}0A` }}
    >
      <Icon className="size-2.5" />
      {label}
    </span>
  )
}
