import { Card } from './Card'
import { FieldDisplay } from '../shared/FieldDisplay'
import { Maveric3DViewer } from './Maveric3DViewer'
import { ModeStrip } from '../shared/ModeStrip'
import { MtqBar, MtqBlock, type AxisTick } from '../shared/MtqBars'
import { TempGauge } from '../shared/TempGauge'
import { fmtQuat, fmtYpr, fmtDateDisplay } from './format'
import {
  qFrom,
  rateFrom,
  mtqFrom,
  adcsTmpFrom,
  anyRateSentinel,
  rateMagnitude,
  deriveThetaAxis,
  quatToYpr,
} from '../shared/type-guards'
import { TEMP_BANDS, tempPercent } from '../shared/zones'
import type { GncState, StatBitfield, TimeBCD, DateBCD } from '../types'
import { colors } from '@/lib/colors'

interface AdcsMtqCardProps {
  state: GncState
  nowMs: number
}

const MTQ_VISUAL_RANGE = 0.25
const MTQ_XY_SAT = 0.2
const MTQ_Z_SAT  = 0.1

// Mirrors MODE_NAMES in mav_gss_lib/missions/maveric/telemetry/gnc_registers/schema.py.
const ADCS_MODES = [
  'Safe',
  'De-tumble',
  'Sun Spin',
  'Sun Point',
  'Fine Point',
  'LVLH',
  'Target Trk',
  'Manual',
]

function mtqPercent(value: number): number {
  const clamped = Math.max(-MTQ_VISUAL_RANGE, Math.min(MTQ_VISUAL_RANGE, value))
  return 50 + (clamped / MTQ_VISUAL_RANGE) * 50
}

const MTQ_TICKS: AxisTick[] = [
  { label: '−0.25', percent: 0,   edge: 'lo' },
  { label: '−0.12', percent: 25 },
  { label: '0',     percent: 50 },
  { label: '+0.12', percent: 75 },
  { label: '+0.25', percent: 100, edge: 'hi' },
]

const ADCS_TEMP_RANGE_TICKS = [
  { label: '−40', percent: tempPercent(-40), edge: 'lo' as const },
  { label: '−25', percent: tempPercent(-25), safeEdge: true },
  { label: '0',   percent: tempPercent(0) },
  { label: '+70', percent: tempPercent(70), safeEdge: true },
  { label: '+90', percent: tempPercent(90), edge: 'hi' as const },
]

export function AdcsMtqCard({ state, nowMs }: AdcsMtqCardProps) {
  const stat = state.STAT
  const time = state.TIME
  const date = state.DATE
  const q = state.Q
  const rate = state.RATE
  const tmp = state.ADCS_TMP
  const mtqUser = state.MTQ_USER

  const statV = stat?.value as StatBitfield | undefined
  const timeV = time?.value as TimeBCD | undefined
  const dateV = date?.value as DateBCD | undefined
  const tmpV = adcsTmpFrom(tmp)

  const qArr = qFrom(q)
  const rateArr = rateFrom(rate)
  const mtqArr = mtqFrom(mtqUser)

  const rateUninit = anyRateSentinel(rateArr)
  const rateMag = rateMagnitude(rateArr)
  const ypr = quatToYpr(qArr)
  const thetaAxis = deriveThetaAxis(qArr)

  const modeChip = statV ? (
    <div
      className="font-mono text-[11px] px-2 py-0.5 rounded-sm"
      style={{
        color: colors.active,
        border: `1px solid ${colors.active}4D`,
      }}
    >
      {statV.MODE_name}
    </div>
  ) : null

  return (
    <Card title="ADCS · MTQ" status={modeChip} className="h-full">
      {/* Local flex wrapper — scoped stretching so the shared Card
          component stays free of layout constraints that other plugin
          cards (Planner, NaviGuider) don't need. */}
      <div className="h-full flex flex-col min-h-0">
      <ModeStrip labels={ADCS_MODES} activeIndex={statV?.MODE} columns={8} />

      <div className="grid grid-cols-2 border-t border-[#1a1a1a] flex-1 min-h-0">
        <div className="border-r border-[#1a1a1a] min-h-0">
          <Maveric3DViewer q={qArr} />
        </div>
        {/* justify-evenly spreads extra vertical height as uniform gaps
            between every row, so when the left column (Planner +
            NaviGuider) makes this card taller the rows stay visually
            balanced instead of pooling empty space at the bottom. */}
        <div className="min-w-0 flex flex-col justify-evenly min-h-0">
          <FieldDisplay
            label="Att Q"
            value={fmtQuat(qArr)}
            receivedAt={q?.t}
            nowMs={nowMs}
          />
          <FieldDisplay
            label="YPR"
            value={ypr ? `${fmtYpr(ypr)} deg` : '—, —, — deg'}
            nowMs={nowMs}
            derived
          />
          <FieldDisplay
            label="θ · axis"
            value={thetaAxis.display}
            nowMs={nowMs}
            derived
          />
          <FieldDisplay
            label="Rate"
            value={rateUninit
              ? '⚠ uninit rad/s'
              : rateArr
                ? `${rateArr.map(v => v.toFixed(4)).join(', ')} rad/s`
                : '—'
            }
            receivedAt={rate?.t}
            nowMs={nowMs}
            forceTone={rateUninit ? 'warning' : undefined}
          />
          <FieldDisplay
            label="|ω|"
            value={rateMag != null ? `${rateMag.toFixed(4)} rad/s` : '—'}
            nowMs={nowMs}
            derived
          />
          <FieldDisplay
            label="Time"
            value={timeV?.display ?? '—'}
            receivedAt={time?.t}
            nowMs={nowMs}
          />
          <FieldDisplay
            label="Date"
            value={fmtDateDisplay(dateV)}
            receivedAt={date?.t}
            nowMs={nowMs}
          />

          <MtqBlock
            title="MTQ_User · Dipole"
            subtitle="A·m² · ±0.2 X,Y · ±0.1 Z"
            ticks={MTQ_TICKS}
          >
            <MtqBar
              axis="MX"
              valueText={mtqArr ? mtqArr[0].toFixed(4) : '—'}
              unit="A·m²"
              kind={{
                type: 'saturation',
                loPercent: mtqPercent(-MTQ_XY_SAT),
                hiPercent: mtqPercent(MTQ_XY_SAT),
              }}
              muted={!mtqArr}
            />
            <MtqBar
              axis="MY"
              valueText={mtqArr ? mtqArr[1].toFixed(4) : '—'}
              unit="A·m²"
              kind={{
                type: 'saturation',
                loPercent: mtqPercent(-MTQ_XY_SAT),
                hiPercent: mtqPercent(MTQ_XY_SAT),
              }}
              muted={!mtqArr}
            />
            <MtqBar
              axis="MZ"
              valueText={mtqArr ? mtqArr[2].toFixed(4) : '—'}
              unit="A·m²"
              kind={{
                type: 'saturation',
                loPercent: mtqPercent(-MTQ_Z_SAT),
                hiPercent: mtqPercent(MTQ_Z_SAT),
              }}
              muted={!mtqArr}
            />
          </MtqBlock>

          <TempGauge
            label="ADCS_TMP"
            celsius={tmpV?.celsius ?? null}
            commFault={tmpV?.comm_fault}
            band={TEMP_BANDS.ADCS_TMP}
            safeLoPercent={tempPercent(TEMP_BANDS.ADCS_TMP.lo)}
            safeHiPercent={tempPercent(TEMP_BANDS.ADCS_TMP.hi)}
            ticks={ADCS_TEMP_RANGE_TICKS}
            receivedAt={tmp?.t}
            nowMs={nowMs}
          />
        </div>
      </div>
      </div>
    </Card>
  )
}
