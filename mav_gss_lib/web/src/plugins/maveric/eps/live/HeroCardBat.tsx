import { memo } from 'react'
import { fmt, formatCurrent } from '../derive'
import type { AlarmLevel, ChargeDir } from '../types'

const AXIS_LO = 6.0
const AXIS_HI = 8.4
const AXIS_RANGE = AXIS_HI - AXIS_LO
const V_LO  = 6.5
const V_NOM = 8.0

function bigTone(alarm: AlarmLevel): string {
  if (alarm === 'danger')  return 'big danger'
  if (alarm === 'caution') return 'big warning'
  if (alarm === 'ok')      return 'big success'
  return 'big muted'
}

function dotClass(dir: ChargeDir, alarm: AlarmLevel): string {
  if (alarm === 'danger')  return 'dot danger'
  if (alarm === 'caution') return 'dot warn'
  if (dir === 'charge')    return 'dot success'
  if (dir === 'discharge') return 'dot warn'
  return 'dot neutral'
}

function dotLabel(dir: ChargeDir): string {
  if (dir === 'charge')    return 'CHG'
  if (dir === 'discharge') return 'DIS'
  return 'IDLE'
}

function chipClass(dir: ChargeDir): string {
  if (dir === 'charge')    return 'chip charge'
  if (dir === 'discharge') return 'chip dis'
  return 'chip idle'
}

function pct(v: number): number {
  const x = (v - AXIS_LO) / AXIS_RANGE
  return Math.max(0, Math.min(1, x)) * 100
}

interface Props {
  V_BAT: number
  I_BAT: number
  prev_V_BAT: number
  chargeDir: ChargeDir
  soc: number | null
  alarm: AlarmLevel
}

function HeroCardBatInner({ V_BAT, I_BAT, prev_V_BAT, chargeDir, soc, alarm }: Props) {
  const hasPrev = Number.isFinite(prev_V_BAT)
  const delta = hasPrev ? V_BAT - prev_V_BAT : NaN
  const deltaClass = !Number.isFinite(delta) || Math.abs(delta) < 0.001
    ? 'd-v flat'
    : delta > 0 ? 'd-v up' : 'd-v down'
  const deltaText = Number.isFinite(delta) ? `${delta >= 0 ? '+' : ''}${delta.toFixed(3)} V` : '—'
  const fill   = Number.isFinite(V_BAT) ? pct(V_BAT) : 0
  const limLo  = pct(V_LO)
  const limNom = pct(V_NOM)

  return (
    <div className="card live" data-component="HeroCard" data-kind="bat">
      <div className="card-head live-bg">
        <div className="card-head-left">
          <span className="card-title">Battery</span>
        </div>
        <div className={dotClass(chargeDir, alarm)} data-state={chargeDir}>
          <span className="sh"></span>
          <span className="lbl">{dotLabel(chargeDir)}</span>
        </div>
      </div>
      <div className="hero-card-body">
        <div className="hero-reading">
          <span className={bigTone(alarm)} data-hk="V_BAT">{fmt(V_BAT, 3)}</span>
          <span className="unit">V</span>
          <span className="hero-sub">
            <span data-hk="I_BAT">{formatCurrent(I_BAT)}</span>
            <span className={chipClass(chargeDir)}>{dotLabel(chargeDir)}</span>
          </span>
        </div>
        <div title="V_BAT · lo 6.5 · nom 8.0 · max 8.4 V">
          <div className="soc-gauge" data-gauge="V_BAT" role="img"
               aria-label={soc !== null ? `Battery SoC ~${Math.round(soc)}%` : 'Battery voltage'}>
            <div className="fill" style={{ width: `${fill}%` }} />
            <div className="lim" style={{ left: `${limLo}%` }} />
            <div className="lim" style={{ left: `${limNom}%`, background: 'var(--state-success)', opacity: 0.85 }} />
          </div>
          <div className="soc-axis">
            <span className="mk edge-l" style={{ left: '0%' }}>6.0</span>
            <span className="mk" style={{ left: `${limLo}%` }}>6.5 lo</span>
            <span className="mk" style={{ left: `${limNom}%` }}>8.0 nom</span>
            <span className="mk edge-r" style={{ left: '100%' }}>8.4 V</span>
          </div>
        </div>
        {hasPrev && (
          <div className="delta-row" data-delta="V_BAT">
            <span className="d-k">Δ</span>
            <span className={deltaClass}>{deltaText}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export const HeroCardBat = memo(HeroCardBatInner)
