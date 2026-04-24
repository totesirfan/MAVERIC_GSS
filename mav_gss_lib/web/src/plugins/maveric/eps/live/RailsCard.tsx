import { memo } from 'react'
import { formatCurrent, fmt } from '../derive'

const NOM_3V3 = 3.3
const NOM_5V0 = 5.0
const TOL_PCT = 5.0
const DEV_CAUTION = 0.05

interface Props {
  V3V3: number; I3V3: number; P3V3: number
  V5V0: number; I5V0: number; P5V0: number
}

function deviationPct(v: number, nom: number): number {
  return ((v - nom) / nom) * 100
}

function railState(v: number, nom: number): 'on' | 'caution' | 'alarm' {
  if (!Number.isFinite(v) || v <= 0) return 'alarm'
  const dev = Math.abs(v - nom) / nom
  if (dev > DEV_CAUTION) return 'caution'
  return 'on'
}

function fmtDevPct(v: number, nom: number): string {
  if (!Number.isFinite(v)) return '—'
  const p = deviationPct(v, nom)
  const sign = p >= 0 ? '+' : ''
  return `${sign}${p.toFixed(2)}%`
}

function tickPos(v: number, nom: number): number {
  if (!Number.isFinite(v)) return 50
  const dev = deviationPct(v, nom)
  const pos = 50 + (dev / TOL_PCT) * 20
  return Math.max(2, Math.min(98, pos))
}

function RailCell({ name, hkKey, V, I, P, nom }: {
  name: string; hkKey: 'V3V3' | 'V5V0'; V: number; I: number; P: number; nom: number;
}) {
  const state = railState(V, nom)
  const cls = state === 'on' ? 'rail-cell reg' : state === 'caution' ? 'rail-cell caution' : 'rail-cell alarm'
  const badge = state === 'alarm' ? 'ALM' : state === 'caution' ? 'DEV' : 'REG'
  return (
    <div className={cls}>
      <div className="top">
        <span className="name">{name}</span>
        <span className="badge">{badge}</span>
      </div>
      <div className="dev">{fmtDevPct(V, nom)}</div>
      <div className="big-v">
        <span data-hk={hkKey}>{fmt(V, 3)}</span>
        <span className="u">V</span>
      </div>
      <div className="ip">
        <span>{formatCurrent(I)}</span>
        <span>{fmt(P, 2)} W</span>
      </div>
      <div className="dev-bar" title={`nom ${nom.toFixed(2)} V · ±${TOL_PCT}% tolerance`}>
        <span className="tol" style={{ left: '30%', right: '30%' }} />
        <span className="center" />
        <span className="tick" style={{ left: `${tickPos(V, nom)}%` }} />
      </div>
    </div>
  )
}

function RailsCardInner({ V3V3, I3V3, P3V3, V5V0, I5V0, P5V0 }: Props) {
  const s3 = railState(V3V3, NOM_3V3)
  const s5 = railState(V5V0, NOM_5V0)
  const allOk  = s3 === 'on' && s5 === 'on'
  const anyAlm = s3 === 'alarm' || s5 === 'alarm'
  const dotCls = allOk ? 'dot success' : anyAlm ? 'dot danger' : 'dot warn'
  const dotLbl = allOk ? 'REG'     : anyAlm ? 'ALM'        : 'DEV'

  return (
    <div className="card" data-component="RailsCard">
      <div className="card-head">
        <div className="card-head-left">
          <span className="card-title">Hot Rails</span>
          <span className="card-sub">UPPM · LPPM · AX100</span>
        </div>
        <div className={dotCls}>
          <span className="sh"></span><span className="lbl">{dotLbl}</span>
        </div>
      </div>
      <div className="rails-body">
        <RailCell name="3V3" hkKey="V3V3" V={V3V3} I={I3V3} P={P3V3} nom={NOM_3V3} />
        <RailCell name="5V"  hkKey="V5V0" V={V5V0} I={I5V0} P={P5V0} nom={NOM_5V0} />
      </div>
    </div>
  )
}

export const RailsCard = memo(RailsCardInner)
