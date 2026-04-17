import { colors } from '@/lib/colors'
import {
  ageMs,
  formatAge,
  staleLevel,
  STALE_OPACITY,
  NO_DATA_OPACITY,
  type StaleLevel,
} from './staleness'

interface FieldDisplayProps {
  label: string
  /** Rendered value. Pass '—' for "no data yet". */
  value: string
  /** ms since epoch when the data was last received. */
  receivedAt?: number | null
  /** "now" — ms. Pass a ref so all fields in a panel share one tick. */
  nowMs: number
  /** Force a tone regardless of staleness (e.g. danger on decode error). */
  forceTone?: 'danger' | 'warning' | 'success' | 'info' | 'neutral'
}

export function FieldDisplay({
  label,
  value,
  receivedAt,
  nowMs,
  forceTone,
}: FieldDisplayProps) {
  const hasData = receivedAt != null
  const age = ageMs(receivedAt ?? null, nowMs)
  const level: StaleLevel = hasData ? staleLevel(age) : 'critical'

  let tone: string = forceTone ?? 'neutral'
  if (!forceTone && hasData) {
    if (level === 'warning') tone = 'warning'
    else if (level === 'critical') tone = 'danger'
  }

  const valueColor =
    tone === 'danger'  ? colors.danger  :
    tone === 'warning' ? colors.warning :
    tone === 'success' ? colors.success :
    tone === 'info'    ? colors.info    :
                         colors.textPrimary

  const opacity = hasData ? STALE_OPACITY[level] : NO_DATA_OPACITY

  return (
    <div
      className="flex items-center justify-between border-b border-[#151515] last:border-b-0 px-3 py-1.5"
      style={{ opacity }}
    >
      <div className="text-[11px] uppercase tracking-wide text-[#8A8A8A] font-sans">
        {label}
      </div>
      <div className="flex items-center gap-2">
        <div
          className="font-mono text-[12px] tabular-nums"
          style={{ color: valueColor }}
        >
          {value}
        </div>
        {hasData && (
          <div className="font-mono text-[11px] text-[#555555] min-w-[28px] text-right">
            {formatAge(age)}
          </div>
        )}
      </div>
    </div>
  )
}
