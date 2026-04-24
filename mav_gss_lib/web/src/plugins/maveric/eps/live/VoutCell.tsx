import { memo } from 'react'
import { formatCurrent, fmt } from '../derive'

const ACTIVE_THRESHOLD_W = 1.0
const LOAD_BAR_FULL_SCALE_W = 5.0

interface Props {
  index: number
  V: number
  I: number
  P: number
  subsystem: string
}

function VoutCellInner({ index, V, I, P, subsystem }: Props) {
  const on = Number.isFinite(V) && V > 0.5
  const cls = on ? 'vout-cell on' : 'vout-cell off'
  const badge = on ? 'ON' : 'OFF'
  const fillPct = Number.isFinite(P) && P > 0
    ? Math.max(0, Math.min(100, (P / LOAD_BAR_FULL_SCALE_W) * 100))
    : 0
  const tickPct = (ACTIVE_THRESHOLD_W / LOAD_BAR_FULL_SCALE_W) * 100

  return (
    <div className={cls} data-component="VoutCell" data-rail={`VOUT${index}`}>
      <div className="top">
        <span className="name">VOUT{index}</span>
        <span className="badge">{badge}</span>
      </div>
      <div className="meta"><span>{subsystem || '—'}</span></div>
      <div className="big-v">
        <span data-hk={`VOUT${index}`}>{fmt(V, 3)}</span>
        <span className="u">V</span>
      </div>
      <div className="ip">
        <span data-hk={`IOUT${index}`}>{formatCurrent(I)}</span>
        <span data-hk={`POUT${index}`}>{fmt(P, 2)} W</span>
      </div>
      <div className="load-bar"
           title={`${fmt(P, 2)} W · active threshold ${ACTIVE_THRESHOLD_W} W · scale 0-${LOAD_BAR_FULL_SCALE_W} W`}>
        <span className="fill" style={{ width: `${fillPct}%` }} />
        <span className="tick" style={{ left: `${tickPct}%` }} />
      </div>
    </div>
  )
}

export const VoutCell = memo(VoutCellInner)
