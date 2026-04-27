import { Card } from './Card'
import { FieldDisplay } from '../shared/FieldDisplay'
import { MtqBar, MtqBlock, type AxisTick } from '../shared/MtqBars'
import { TempGauge } from '../shared/TempGauge'
import { nvgSensorFrom, nvgNumericValues, magMagnitude } from '../shared/type-guards'
import { TEMP_BANDS, tempPercent } from '../shared/zones'
import type { GncState, NvgStatus } from '../types'
import { colors } from '@/lib/colors'

interface NaviGuiderCardProps {
  state: GncState
  nowMs: number
}

const RAD_TO_DEG = 180 / Math.PI

// Gyroscope bars visualize ±2 °/s.
const GYRO_VISUAL_RANGE_DPS = 2
function gyroPercent(valueDeg: number): number {
  const clamped = Math.max(-GYRO_VISUAL_RANGE_DPS, Math.min(GYRO_VISUAL_RANGE_DPS, valueDeg))
  return 50 + (clamped / GYRO_VISUAL_RANGE_DPS) * 50
}

const GYRO_TICKS: AxisTick[] = [
  { label: '−2', percent: 0,   edge: 'lo' },
  { label: '−1', percent: 25 },
  { label: '0',  percent: 50 },
  { label: '+1', percent: 75 },
  { label: '+2', percent: 100, edge: 'hi' },
]

const NVG_TEMP_RANGE_TICKS = [
  { label: '−40', percent: tempPercent(-40), edge: 'lo' as const },
  { label: '−20', percent: tempPercent(-20), safeEdge: true },
  { label: '0',   percent: tempPercent(0) },
  { label: '+85', percent: tempPercent(85), safeEdge: true },
]

function fmtNvgVec(vals: (number | null)[] | null, count: number, decimals = 2): string {
  if (!vals || vals.length < count) return '—'
  return vals.slice(0, count).map(v => v != null ? v.toFixed(decimals) : '—').join(', ')
}

type BarKind =
  | { type: 'fill'; leftPercent: number; widthPercent: number }
  | { type: 'none' }

function gyroBarValue(value: number | null): { text: string; kind: BarKind } {
  if (value == null) return { text: '—', kind: { type: 'none' } }
  const pct = gyroPercent(value)
  const text = value.toFixed(3)
  // Draw from center (50%) toward the value's position.
  const kind: BarKind = pct >= 50
    ? { type: 'fill', leftPercent: 50, widthPercent: pct - 50 }
    : { type: 'fill', leftPercent: pct, widthPercent: 50 - pct }
  return { text, kind }
}

export function NaviGuiderCard({ state, nowMs }: NaviGuiderCardProps) {
  const status = state.nvg_status
  const gyro = state.gyroscope
  const mag = state.magnetometer
  const temp = state.temperature

  const statusV = status?.value as NvgStatus | undefined

  const gyroSensor = nvgSensorFrom(gyro)
  const gyroRadPerSec = gyroSensor ? nvgNumericValues(gyroSensor).slice(0, 3) : null
  const gyroDegPerSec = gyroRadPerSec
    ? gyroRadPerSec.map(v => v != null ? v * RAD_TO_DEG : null)
    : null

  const magSensor = nvgSensorFrom(mag)
  const magValues = magSensor ? nvgNumericValues(magSensor).slice(0, 3) : null
  const magNumeric = magValues?.every((v): v is number => v != null) ? magValues : null
  const magMag = magNumeric ? magMagnitude(magNumeric) : null

  const tempSensor = nvgSensorFrom(temp)
  const tempValues = tempSensor ? nvgNumericValues(tempSensor) : null
  const tempCelsius = tempValues && typeof tempValues[0] === 'number' ? tempValues[0] : null

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
      <MtqBlock
        title="Gyroscope · Body Frame"
        subtitle="NVG sensor 4 · scale ±2 °/s"
        ticks={GYRO_TICKS}
      >
        {(['ωX', 'ωY', 'ωZ'] as const).map((axis, i) => {
          const v = gyroDegPerSec?.[i] ?? null
          const { text, kind } = gyroBarValue(v)
          return (
            <MtqBar
              key={axis}
              axis={axis}
              valueText={text}
              unit="°/s"
              kind={kind}
              muted={v == null}
            />
          )
        })}
      </MtqBlock>

      <FieldDisplay
        label="Mag XYZ"
        value={magValues ? `${fmtNvgVec(magValues, 3)} µT` : '—'}
        receivedAt={mag?.t}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Mag ‖B‖"
        value={magMag != null ? `${magMag.toFixed(1)} µT` : '—'}
        nowMs={nowMs}
        derived
      />

      <TempGauge
        label="NVG_TMP"
        celsius={tempCelsius}
        band={TEMP_BANDS.FSS_TMP1}
        safeLoPercent={tempPercent(TEMP_BANDS.FSS_TMP1.lo)}
        safeHiPercent={tempPercent(TEMP_BANDS.FSS_TMP1.hi)}
        ticks={NVG_TEMP_RANGE_TICKS}
        receivedAt={temp?.t}
        nowMs={nowMs}
      />
    </Card>
  )
}
