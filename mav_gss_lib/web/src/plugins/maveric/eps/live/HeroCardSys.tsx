import { memo } from 'react'
import { fmt, clamp } from '../derive'
import type { AlarmLevel } from '../types'

// V_SYS can drop lower than V_BUS during safe-mode / battery-only operation.
// Calibrated vs bench (~7.7 V with AC on) and the brown-out threshold.
const AXIS_LO = 5.0
const AXIS_HI = 9.0
const AXIS_RANGE = AXIS_HI - AXIS_LO
const V_LO  = 5.5
const V_NOM = 7.0
const V_HI  = 8.5

function bigTone(alarm: AlarmLevel): string {
  if (alarm === 'danger')  return 'big danger'
  if (alarm === 'caution') return 'big warning'
  if (alarm === 'ok')      return 'big success'
  return 'big muted'
}

function dotClass(alarm: AlarmLevel): string {
  if (alarm === 'danger')  return 'dot danger'
  if (alarm === 'caution') return 'dot warn'
  if (alarm === 'ok')      return 'dot success'
  return 'dot neutral'
}

function dotLabel(alarm: AlarmLevel): string {
  if (alarm === 'danger')  return 'ALM'
  if (alarm === 'caution') return 'CAU'
  if (alarm === 'ok')      return 'NOM'
  return '—'
}

function pct(v: number): number {
  return (clamp(v, AXIS_LO, AXIS_HI) - AXIS_LO) / AXIS_RANGE * 100
}

interface Props {
  V_SYS: number
  prev_V_SYS: number
  alarm: AlarmLevel
}

function HeroCardSysInner({ V_SYS, prev_V_SYS, alarm }: Props) {
  const hasPrev = Number.isFinite(prev_V_SYS)
  const delta = hasPrev ? V_SYS - prev_V_SYS : NaN
  const deltaClass = !Number.isFinite(delta) || Math.abs(delta) < 0.001
    ? 'd-v flat'
    : delta > 0 ? 'd-v up' : 'd-v down'
  const deltaText = Number.isFinite(delta) ? `${delta >= 0 ? '+' : ''}${delta.toFixed(3)} V` : '—'
  const fill   = Number.isFinite(V_SYS) ? pct(V_SYS) : 0
  const limLo  = pct(V_LO)
  const limNom = pct(V_NOM)
  const limHi  = pct(V_HI)

  return (
    <div className="card live" data-component="HeroCard" data-kind="sys">
      <div className="card-head live-bg">
        <div className="card-head-left">
          <span className="card-title">System</span>
        </div>
        <div className={dotClass(alarm)}>
          <span className="sh"></span><span className="lbl">{dotLabel(alarm)}</span>
        </div>
      </div>
      <div className="hero-card-body">
        <div className="hero-reading">
          <span className={bigTone(alarm)} data-hk="V_SYS">{fmt(V_SYS, 3)}</span>
          <span className="unit">V</span>
          <span className="hero-sub">V_SYS</span>
        </div>
        <div title="V_SYS · lo 5.5 brown-out · nom 7.0 · hi 8.5">
          <div className="soc-gauge" data-gauge="V_SYS" role="img"
               aria-label={`V_SYS ${fmt(V_SYS, 3)} V`}>
            <div className="fill" style={{ width: `${fill}%`, background: 'var(--state-info)' }} />
            <div className="lim" style={{ left: `${limLo}%` }} />
            <div className="lim" style={{ left: `${limNom}%` }} />
            <div className="lim" style={{ left: `${limHi}%` }} />
            {Number.isFinite(V_SYS) && <div className="marker" style={{ left: `${fill}%` }} />}
          </div>
          <div className="soc-axis">
            <span className="mk edge-l" style={{ left: '0%' }}>5.0</span>
            <span className="mk" style={{ left: `${limLo}%` }}>5.5 lo</span>
            <span className="mk" style={{ left: `${limNom}%` }}>7.0 nom</span>
            <span className="mk edge-r" style={{ left: '100%' }}>9.0 V</span>
          </div>
        </div>
        {hasPrev && (
          <div className="delta-row" data-delta="V_SYS">
            <span className="d-k">Δ</span>
            <span className={deltaClass}>{deltaText}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export const HeroCardSys = memo(HeroCardSysInner)
