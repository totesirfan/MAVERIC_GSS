import { Card } from './Card'
import { FieldDisplay } from '../shared/FieldDisplay'
import { ModeStrip } from '../shared/ModeStrip'
import type { GncState, GncMode } from '../types'
import { colors } from '@/lib/colors'

interface GncPlannerCardProps {
  state: GncState
  nowMs: number
}

const PLANNER_MODES = ['Safe', 'Auto', 'Manual']

const numOrNull = (snap: { value?: unknown } | undefined): number | null =>
  typeof snap?.value === 'number' ? snap.value : null

/** GNC Planner panel.
 *  Mode:     gnc_get_mode RES (0=Safe, 1=Auto, 2=Manual)
 *  Counters: tlm_beacon (unexpected_safe / unexpected_detumble / sunspin)
 *  Sources:  RATE_SRC / MAG_SRC from tlm_beacon (raw int source
 *            selector; no enum in repo, display verbatim).
 */
export function GncPlannerCard({ state, nowMs }: GncPlannerCardProps) {
  const mode        = state.GNC_MODE
  const safeCnt     = state.unexpected_safe
  const detumbleCnt = state.unexpected_detumble
  const sunspinCnt  = state.sunspin
  const gyroSrc     = state.RATE_SRC
  const magSrc      = state.MAG_SRC

  const modeV = mode?.value as GncMode | undefined
  const safeV     = numOrNull(safeCnt)
  const detumbleV = numOrNull(detumbleCnt)
  const sunspinV  = numOrNull(sunspinCnt)
  const gyroSrcV  = numOrNull(gyroSrc)
  const magSrcV   = numOrNull(magSrc)

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
        label="Unexpected Safe"
        value={safeV != null ? String(safeV) : '—'}
        receivedAt={safeCnt?.t}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Unexpected Detumble"
        value={detumbleV != null ? String(detumbleV) : '—'}
        receivedAt={detumbleCnt?.t}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Sunspin"
        value={sunspinV != null ? String(sunspinV) : '—'}
        receivedAt={sunspinCnt?.t}
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
