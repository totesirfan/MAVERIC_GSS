import { colors } from '@/lib/colors'
import {
  ageMs,
  formatAge,
  staleLevel,
  STALE_OPACITY,
  NO_DATA_OPACITY,
  type StaleLevel,
} from './staleness'

type Polarity = 'fault' | 'status'
// fault: true=bad (red), false=nominal (green)
// status: true=on (cyan/green), false=off (neutral)

interface FlagDotProps {
  label: string
  value: boolean | null | undefined
  /** Interpretation of `true`. Default 'fault' — most flag rows are fault flags. */
  polarity?: Polarity
  /** Server-anchored epoch ms when the source register was last received. */
  receivedAtMs?: number | null
  /** Current clock tick, shared across the panel. */
  nowMs: number
}

export function FlagDot({
  label,
  value,
  polarity = 'fault',
  receivedAtMs,
  nowMs,
}: FlagDotProps) {
  const noData = value === null || value === undefined
  const age = ageMs(receivedAtMs ?? null, nowMs)
  const level: StaleLevel = receivedAtMs != null ? staleLevel(age) : 'critical'

  let dotColor: string
  let text: string

  if (noData) {
    dotColor = colors.neutral
    text = '—'
  } else if (polarity === 'fault') {
    dotColor = value ? colors.danger : colors.success
    text = value ? 'FAULT' : 'OK'
  } else {
    dotColor = value ? colors.active : colors.neutral
    text = value ? 'ON' : 'OFF'
  }

  const opacity = receivedAtMs != null ? STALE_OPACITY[level] : NO_DATA_OPACITY

  return (
    <div
      className="flex flex-col items-center justify-center px-2 py-2 border-r border-[#1a1a1a] last:border-r-0"
      style={{ opacity }}
    >
      <div className="text-[11px] uppercase tracking-wide text-[#8A8A8A] text-center mb-1">
        {label}
      </div>
      <div className="flex items-center gap-1.5">
        <span
          className="inline-block rounded-full"
          style={{
            width: 9,
            height: 9,
            backgroundColor: dotColor,
            boxShadow: noData ? 'none' : `0 0 4px ${dotColor}80`,
          }}
          aria-hidden
        />
        <span className="font-mono text-[11px]" style={{ color: dotColor }}>
          {text}
        </span>
      </div>
      <div className="font-mono text-[11px] text-[#555555] mt-0.5 min-h-[14px]">
        {receivedAtMs != null ? formatAge(age) : ''}
      </div>
    </div>
  )
}
