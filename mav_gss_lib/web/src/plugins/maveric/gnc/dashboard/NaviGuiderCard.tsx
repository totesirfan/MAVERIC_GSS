import { Card } from './Card'
import { FieldDisplay } from '../shared/FieldDisplay'
import type { GncState, NvgSensor, NvgStatus } from '../types'
import { colors } from '@/lib/colors'

interface NaviGuiderCardProps {
  state: GncState
  nowMs: number
}

/** Extract the leading XYZ values from an NvgSensor. Returns '—' if
 *  fewer than `count` numeric values arrived (e.g. when the MAVERIC
 *  cache only holds a truncated payload). */
function fmtNvgVec(snap: NvgSensor | undefined, count: number, decimals = 4): string {
  if (!snap) return '—'
  const vals = snap.values
  if (!vals || vals.length < count) return '—'
  const head = vals.slice(0, count).map((v) =>
    typeof v === 'number' ? v.toFixed(decimals) : String(v),
  )
  return head.join(', ')
}

function fmtNvgScalar(snap: NvgSensor | undefined, suffix: string, decimals = 2): string {
  if (!snap) return '—'
  const vals = snap.values
  if (!vals || vals.length < 1) return '—'
  const v = vals[0]
  if (typeof v !== 'number') return '—'
  return `${v.toFixed(decimals)}${suffix}`
}

/** rad/s → deg/s (mockup labels gyro in deg/s; NaviGuider manual returns rad/s). */
function fmtGyroDegPerSec(snap: NvgSensor | undefined, decimals = 3): string {
  if (!snap) return '—'
  const vals = snap.values
  if (!vals || vals.length < 3) return '—'
  const xyz = vals.slice(0, 3).map((v) =>
    typeof v === 'number' ? ((v * 180) / Math.PI).toFixed(decimals) : String(v),
  )
  return xyz.join(', ')
}

export function NaviGuiderCard({ state, nowMs }: NaviGuiderCardProps) {
  const status = state.NVG_STATUS
  const orient = state.NVG_ORIENTATION
  const gyro   = state.NVG_GYROSCOPE
  const mag    = state.NVG_MAGNETOMETER
  const temp   = state.NVG_TEMPERATURE

  const statusV = status?.value as NvgStatus | undefined
  const orientV = orient?.value as NvgSensor | undefined
  const gyroV   = gyro?.value   as NvgSensor | undefined
  const magV    = mag?.value    as NvgSensor | undefined
  const tempV   = temp?.value   as NvgSensor | undefined

  const statusChip = statusV ? (
    <div
      className="font-mono text-[11px] px-2 py-0.5 rounded-sm"
      style={{
        color: statusV.status === 1 ? colors.success : colors.neutral,
        backgroundColor: 'transparent',
        border: `1px solid ${(statusV.status === 1 ? colors.success : colors.neutral)}4D`,
      }}
    >
      {statusV.label}
    </div>
  ) : null

  return (
    <Card title="NaviGuider" status={statusChip}>
      <FieldDisplay
        label="Status"
        value={statusV?.label ?? '—'}
        receivedAt={status?.received_at_ms}
        nowMs={nowMs}
        forceTone={statusV?.status === 1 ? 'success' : statusV ? 'neutral' : undefined}
      />
      <FieldDisplay
        label="Orientation"
        value={orientV ? `${fmtNvgVec(orientV, 3, 2)} deg` : '—'}
        receivedAt={orient?.received_at_ms}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Gyroscope"
        value={gyroV ? `${fmtGyroDegPerSec(gyroV)} deg/s` : '—'}
        receivedAt={gyro?.received_at_ms}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Temperature"
        value={fmtNvgScalar(tempV, ' °C', 1)}
        receivedAt={temp?.received_at_ms}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Magnetometer"
        value={magV ? `${fmtNvgVec(magV, 3, 2)} µT` : '—'}
        receivedAt={mag?.received_at_ms}
        nowMs={nowMs}
      />
    </Card>
  )
}
