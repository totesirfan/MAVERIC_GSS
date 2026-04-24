import { memo } from 'react'
import { fmt, clamp, formatCurrent } from '../derive'
import type { AlarmLevel } from '../types'

const AXIS_LO = 6.0
const AXIS_HI = 9.5
const AXIS_RANGE = AXIS_HI - AXIS_LO
const ALARM_LO = 6.5
const NOM_LO = 8.5
const ALARM_HI = 9.5

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
  V_BUS: number
  I_BUS: number
  prev_V_BUS: number
  alarm: AlarmLevel
}

function HeroCardBusInner({ V_BUS, I_BUS, prev_V_BUS, alarm }: Props) {
  const hasPrev = Number.isFinite(prev_V_BUS)
  const delta = hasPrev ? V_BUS - prev_V_BUS : NaN
  const deltaClass = !Number.isFinite(delta) || Math.abs(delta) < 0.001
    ? 'd-v flat'
    : delta > 0 ? 'd-v up' : 'd-v down'
  const deltaText = Number.isFinite(delta) ? `${delta >= 0 ? '+' : ''}${delta.toFixed(3)} V` : '—'
  const pBusText = Number.isFinite(V_BUS) && Number.isFinite(I_BUS)
    ? `${(V_BUS * I_BUS).toFixed(2)} W`
    : '—'
  const fill   = Number.isFinite(V_BUS) ? pct(V_BUS) : 0
  const limLo  = pct(ALARM_LO)
  const limNom = pct(NOM_LO)
  const limHi  = pct(ALARM_HI)

  return (
    <div className="card live" data-component="HeroCard" data-kind="bus">
      <div className="card-head live-bg">
        <div className="card-head-left">
          <span className="card-title">Bus</span>
        </div>
        <div className={dotClass(alarm)}>
          <span className="sh"></span><span className="lbl">{dotLabel(alarm)}</span>
        </div>
      </div>
      <div className="hero-card-body">
        <div className="hero-reading">
          <span className={bigTone(alarm)} data-hk="V_BUS">{fmt(V_BUS, 3)}</span>
          <span className="unit">V</span>
          <span className="hero-sub" style={{ marginLeft: 'auto' }}>
            <span data-hk="I_BUS">{formatCurrent(I_BUS)}</span>
            {' · '}
            <span className="derived" title="P_BUS = V_BUS × I_BUS (derived)" data-derived="P_BUS">{pBusText}</span>
          </span>
        </div>
        <div title="V_BUS · lo 6.5 · nom 8.5–9.3 · hi 9.5">
          <div className="soc-gauge" data-gauge="V_BUS" role="img"
               aria-label={`V_BUS ${fmt(V_BUS, 3)} V`}>
            <div className="fill" style={{ width: `${fill}%`, background: 'var(--state-info)' }} />
            <div className="lim" style={{ left: `${limLo}%` }} />
            <div className="lim" style={{ left: `${limNom}%`, background: 'var(--state-success)', opacity: 0.85 }} />
            <div className="lim" style={{ left: `${limHi}%`,  background: 'var(--state-danger)',  opacity: 0.85 }} />
          </div>
          <div className="soc-axis">
            <span className="mk edge-l" style={{ left: '0%' }}>6.0</span>
            <span className="mk" style={{ left: `${limLo}%` }}>6.5 lo</span>
            <span className="mk" style={{ left: `${limNom}%` }}>8.5 nom</span>
            <span className="mk edge-r" style={{ left: `${limHi}%` }}>9.5 V</span>
          </div>
        </div>
        {hasPrev && (
          <div className="delta-row" data-delta="V_BUS" title="Change since previous packet">
            <span className="d-k">Δ</span>
            <span className={deltaClass}>{deltaText}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export const HeroCardBus = memo(HeroCardBusInner)
