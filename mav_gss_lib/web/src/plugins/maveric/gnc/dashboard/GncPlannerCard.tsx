import { Card } from './Card'
import { FieldDisplay } from '../shared/FieldDisplay'
import { ModeStrip } from '../shared/ModeStrip'
import type { GncState, GncMode, GncCounters } from '../types'
import { colors } from '@/lib/colors'

interface GncPlannerCardProps {
  state: GncState
  nowMs: number
}

const PLANNER_MODES = ['Safe', 'Auto', 'Manual']

/** GNC Planner panel.
 *  Mode:     gnc_get_mode RES (0=Safe, 1=Auto, 2=Manual)
 *  Counters: gnc_get_cnts RES (Unexpected Safe / Detumble / Sunspin)
 *  Sources:  GYRO_RATE_SRC / MAG_SRC from tlm_beacon (raw int source
 *            selector; no enum in repo, display verbatim).
 */
export function GncPlannerCard({ state, nowMs }: GncPlannerCardProps) {
  const mode     = state.GNC_MODE
  const counters = state.GNC_COUNTERS
  const gyroSrc  = state.GYRO_RATE_SRC
  const magSrc   = state.MAG_SRC

  const modeV = mode?.value as GncMode | undefined
  const cntV  = counters?.value as GncCounters | undefined
  const gyroSrcV = typeof gyroSrc?.value === 'number' ? gyroSrc.value : null
  const magSrcV  = typeof magSrc?.value === 'number' ? magSrc.value : null

  const modeChip = modeV ? (
    <div
      className="font-mono text-[11px] px-2 py-0.5 rounded-sm"
      style={{
        color: colors.active,
        border: `1px solid ${colors.active}4D`,
      }}
    >
      {modeV.mode_name}
    </div>
  ) : null

  return (
    <Card title="GNC Planner" status={modeChip}>
      <ModeStrip labels={PLANNER_MODES} activeIndex={modeV?.mode} />

      <FieldDisplay
        label="Reboot"
        value={cntV != null ? String(cntV.reboot) : '—'}
        receivedAt={counters?.t}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="De-Tumble"
        value={cntV != null ? String(cntV.detumble) : '—'}
        receivedAt={counters?.t}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Sunspin"
        value={cntV != null ? String(cntV.sunspin) : '—'}
        receivedAt={counters?.t}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Gyro Src"
        value={gyroSrcV != null ? String(gyroSrcV) : '—'}
        receivedAt={gyroSrc?.t}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Mag Src"
        value={magSrcV != null ? String(magSrcV) : '—'}
        receivedAt={magSrc?.t}
        nowMs={nowMs}
      />
    </Card>
  )
}
