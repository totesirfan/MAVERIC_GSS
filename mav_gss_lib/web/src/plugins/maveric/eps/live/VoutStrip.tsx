import { memo } from 'react'
import { VoutCell } from './VoutCell'
import { FIELD_DEF_BY_NAME, type EpsFieldMap, type EpsFieldName } from '../types'

interface Props {
  fields: EpsFieldMap
}

function subsysFor(index: number): string {
  const name = `VOUT${index}` as EpsFieldName
  return FIELD_DEF_BY_NAME[name]?.subsystem ?? ''
}

function pick(fields: EpsFieldMap, k: EpsFieldName): number {
  const v = fields[k]
  return typeof v === 'number' ? v : NaN
}

function VoutStripInner({ fields }: Props) {
  let onCount = 0
  let totalLoadW = 0
  const cells: { idx: number; V: number; I: number; P: number }[] = []
  for (let idx = 1; idx <= 6; idx++) {
    const V = pick(fields, `VOUT${idx}` as EpsFieldName)
    const I = pick(fields, `IOUT${idx}` as EpsFieldName)
    const P = pick(fields, `POUT${idx}` as EpsFieldName)
    cells.push({ idx, V, I, P })
    if (Number.isFinite(V) && V > 0.5) onCount += 1
    if (Number.isFinite(P)) totalLoadW += P
  }
  const offCount = 6 - onCount

  return (
    <div className="card" data-component="VoutStrip">
      <div className="card-head">
        <div className="card-head-left">
          <span className="card-title">Switched Outputs</span>
          <span className="card-sub">VOUT1-3 (3V3) · VOUT4-6 (5V)</span>
        </div>
        <span className="card-sub">
          <span style={{ color: 'var(--state-success)' }}>{onCount} ON</span>
          {' · '}{offCount} OFF · <span className="derived" title="Σ POUT1..6 (derived)">{totalLoadW.toFixed(2)} W</span>
        </span>
      </div>
      <div className="vout-strip">
        {cells.map((c) => (
          <VoutCell
            key={c.idx}
            index={c.idx}
            V={c.V}
            I={c.I}
            P={c.P}
            subsystem={subsysFor(c.idx)}
          />
        ))}
      </div>
    </div>
  )
}

export const VoutStrip = memo(VoutStripInner)
