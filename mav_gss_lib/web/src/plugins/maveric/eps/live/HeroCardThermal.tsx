import { memo } from 'react'
import { fmt, clamp } from '../derive'
import type { AlarmLevel } from '../types'

const AXIS_LO = -10
const AXIS_HI = 85
const AXIS_RANGE = AXIS_HI - AXIS_LO
const T_COLD = 0
const T_HOT  = 70
const T_JCT  = 85

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

function pct(t: number): number {
  return (clamp(t, AXIS_LO, AXIS_HI) - AXIS_LO) / AXIS_RANGE * 100
}

interface Props {
  T_DIE: number
  TS_ADC: number
  prev_T_DIE: number
  etaSeconds: number | null
  alarm: AlarmLevel
}

function HeroCardThermalInner({ T_DIE, TS_ADC, prev_T_DIE, etaSeconds, alarm }: Props) {
  const hasPrev = Number.isFinite(prev_T_DIE)
  const delta = hasPrev ? T_DIE - prev_T_DIE : NaN
  const deltaClass = !Number.isFinite(delta) || Math.abs(delta) < 0.05
    ? 'd-v flat'
    : delta > 0 ? 'd-v up' : 'd-v down'
  const deltaText = Number.isFinite(delta) ? `${delta >= 0 ? '+' : ''}${delta.toFixed(1)} °C` : '—'
  const fill    = Number.isFinite(T_DIE) ? pct(T_DIE) : 0
  const limCold = pct(T_COLD)
  const limHot  = pct(T_HOT)
  const limJct  = pct(T_JCT)
  const etaText = etaSeconds !== null && Number.isFinite(etaSeconds)
    ? `η ~ ${etaSeconds < 600 ? `${Math.round(etaSeconds)} s` : `${Math.round(etaSeconds / 60)} min`}`
    : 'η steady'

  return (
    <div className="card live" data-component="HeroCard" data-kind="therm">
      <div className="card-head live-bg">
        <div className="card-head-left">
          <span className="card-title">Thermal</span>
          <span className="card-sub">T_DIE · TS_ADC</span>
        </div>
        <div className={dotClass(alarm)}>
          <span className="sh"></span><span className="lbl">{dotLabel(alarm)}</span>
        </div>
      </div>
      <div className="hero-card-body">
        <div className="hero-reading">
          <span className={bigTone(alarm)} data-hk="T_DIE">{fmt(T_DIE, 1)}</span>
          <span className="unit">°C</span>
          <span className="hero-sub">
            TS_ADC <span data-hk="TS_ADC">{Number.isFinite(TS_ADC) ? TS_ADC.toFixed(1) : '—'}%</span>
          </span>
        </div>
        <div title="T_DIE · cold 0 · hot 70 · junction-limit 85 °C">
          <div className="soc-gauge" data-gauge="T_DIE" role="img"
               aria-label={`T_DIE ${fmt(T_DIE, 1)} °C`}>
            <div className="fill" style={{ width: `${fill}%`, background: 'var(--state-active)' }} />
            <div className="lim" style={{ left: `${limCold}%` }} />
            <div className="lim" style={{ left: `${limHot}%` }} />
            <div className="lim" style={{ left: `${limJct}%` }} />
            {Number.isFinite(T_DIE) && <div className="marker" style={{ left: `${fill}%` }} />}
          </div>
          <div className="soc-axis">
            <span className="mk edge-l" style={{ left: '0%' }}>−10</span>
            <span className="mk" style={{ left: `${limCold}%` }}>0 cold</span>
            <span className="mk" style={{ left: `${limHot}%` }}>70 hot</span>
            <span className="mk edge-r" style={{ left: '100%' }}>85 °C</span>
          </div>
        </div>
        {hasPrev && (
          <div className="delta-row" data-delta="T_DIE">
            <span className="d-k">Δ</span>
            <span className={deltaClass}>{deltaText}</span>
            <span className="d-steady">{etaText}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export const HeroCardThermal = memo(HeroCardThermalInner)
