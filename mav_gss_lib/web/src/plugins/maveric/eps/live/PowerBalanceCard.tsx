import { memo, useMemo } from 'react'
import {
  batteryChargePower,
  batteryInputPower,
  deriveEpsBoardPower,
  derivePAC,
  efficiency,
  MEASURED_LOAD_KEYS,
  measuredLoadPower,
} from '../derive'
import type { EpsFieldMap, EpsFieldName } from '../types'

interface Props {
  fields: EpsFieldMap
  field_t?: Partial<Record<EpsFieldName, number>>
}

function finite(v: number | undefined): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : 0
}

interface Segment {
  key: string
  kind: 'solar' | 'solar-aux' | 'solar-idle' | 'ac' | 'vout-on' | 'rail' | 'rail-idle' | 'deficit' | 'surplus' | 'stale'
  watts: number
  label?: string
  sub?: string
}

const BUS_BALANCE_KEYS: readonly EpsFieldName[] = ['V_BUS', 'I_BUS', 'V_BAT', 'I_BAT']
const BALANCE_SNAPSHOT_WINDOW_MS = 1000

function newestTimestamp(
  field_t: Partial<Record<EpsFieldName, number>>,
  keys: readonly EpsFieldName[],
): number | null {
  let newest = -Infinity
  for (const k of keys) {
    const t = field_t[k]
    if (typeof t === 'number' && Number.isFinite(t) && t > newest) newest = t
  }
  return Number.isFinite(newest) ? newest : null
}

function coherentLoadSnapshot(field_t: Props['field_t']): boolean {
  if (!field_t) return true
  const busT = newestTimestamp(field_t, BUS_BALANCE_KEYS)
  const loadT = newestTimestamp(field_t, MEASURED_LOAD_KEYS)
  if (busT === null || loadT === null) return false
  return Math.abs(busT - loadT) <= BALANCE_SNAPSHOT_WINDOW_MS
}

function PowerBalanceCardInner({ fields, field_t }: Props) {
  const loadsCoherent = useMemo(() => coherentLoadSnapshot(field_t), [field_t])
  const psin = finite(fields.PSIN1) + finite(fields.PSIN2) + finite(fields.PSIN3)
  const pAc = useMemo(() => derivePAC(fields) ?? 0, [fields])
  const knownLoads = loadsCoherent ? measuredLoadPower(fields) : 0
  const epsBoard = loadsCoherent ? deriveEpsBoardPower(fields) ?? 0 : 0
  const batInput = batteryInputPower(fields, knownLoads + epsBoard)
  const batDischarge = batInput.watts
  const batCharge    = batteryChargePower(fields)

  const eta = efficiency(fields, null)

  const inSegs: Segment[] = []
  if (finite(fields.PSIN1) > 0.01) inSegs.push({
    key: 'psin1', kind: 'solar', watts: finite(fields.PSIN1),
    label: `PSIN1 ${finite(fields.PSIN1).toFixed(2)} W`,
    sub: `${finite(fields.VSIN1).toFixed(2)} V · ${(finite(fields.ISIN1) * 1000).toFixed(0)} mA`,
  })
  if (finite(fields.PSIN2) > 0.01) inSegs.push({
    key: 'psin2', kind: 'solar-aux', watts: finite(fields.PSIN2),
    label: `PSIN2 ${finite(fields.PSIN2).toFixed(2)} W`,
    sub: `${finite(fields.VSIN2).toFixed(2)} V · ${(finite(fields.ISIN2) * 1000).toFixed(0)} mA`,
  })
  if (finite(fields.PSIN3) > 0.01) inSegs.push({
    key: 'psin3', kind: 'solar-aux', watts: finite(fields.PSIN3),
    label: `PSIN3 ${finite(fields.PSIN3).toFixed(2)} W`,
    sub: `${finite(fields.VSIN3).toFixed(2)} V · ${(finite(fields.ISIN3) * 1000).toFixed(0)} mA`,
  })
  if (pAc > 0.01) {
    const ac2 = finite(fields.V_AC2); const ac1 = finite(fields.V_AC1)
    const vAc = ac2 > 1 ? ac2 : ac1 > 1 ? ac1 : null
    const acLabel = ac2 > 1 ? 'AC2' : ac1 > 1 ? 'AC1' : 'AC'
    inSegs.push({
      key: 'ac', kind: 'ac', watts: pAc,
      label: `${acLabel} · ${pAc.toFixed(2)} W`,
      sub: vAc !== null ? `${vAc.toFixed(2)} V` : '— V',
    })
  }
  if (batDischarge > 0.01) {
    const sub = batInput.derivedFromLoads
      ? `load-derived · raw ${batInput.measuredWatts.toFixed(2)} W`
      : 'covering'
    inSegs.push({
      key: 'bat-dis', kind: 'deficit', watts: batDischarge,
      label: `BAT ${batDischarge.toFixed(2)} W`, sub,
    })
  }

  const outSegs: Segment[] = []
  if (loadsCoherent) {
    for (let i = 1; i <= 6; i++) {
      const p = finite((fields as Record<string, number>)[`POUT${i}`])
      if (p > 0.01) {
        const iA = finite((fields as Record<string, number>)[`IOUT${i}`])
        outSegs.push({
          key: `pout${i}`, kind: 'vout-on', watts: p,
          label: `VOUT${i} ${p.toFixed(2)} W`,
          sub: `${(iA * 1000).toFixed(0)} mA`,
        })
      }
    }
    // Hot Rails always render — they are always-on keep-alive per spec.
    // When HK hasn't arrived yet (no fields.P3V3 / P5V0), show idle
    // placeholders so operators see the slot reserved instead of wondering
    // if rails are off.
    const hasP3V3 = typeof fields.P3V3 === 'number' && Number.isFinite(fields.P3V3) && fields.P3V3 > 0.01
    const hasP5V0 = typeof fields.P5V0 === 'number' && Number.isFinite(fields.P5V0) && fields.P5V0 > 0.01
    if (hasP3V3) {
      outSegs.push({
        key: 'p3v3', kind: 'rail', watts: finite(fields.P3V3),
        label: `3V3 · ${finite(fields.P3V3).toFixed(2)} W`,
        sub: `HOT RAIL · ${(finite(fields.I3V3) * 1000).toFixed(0)} mA`,
      })
    } else {
      outSegs.push({ key: 'p3v3', kind: 'rail-idle', watts: 0, label: '3V3', sub: 'HOT RAIL · — W' })
    }
    if (hasP5V0) {
      outSegs.push({
        key: 'p5v0', kind: 'rail', watts: finite(fields.P5V0),
        label: `5V · ${finite(fields.P5V0).toFixed(2)} W`,
        sub: `HOT RAIL · ${(finite(fields.I5V0) * 1000).toFixed(0)} mA`,
      })
    } else {
      outSegs.push({ key: 'p5v0', kind: 'rail-idle', watts: 0, label: '5V', sub: 'HOT RAIL · — W' })
    }
    if (epsBoard > 0.01) outSegs.push({
      key: 'eps-board', kind: 'solar-idle', watts: epsBoard,
      label: `EPS board ${epsBoard.toFixed(2)} W`, sub: 'MCU + quiescent',
    })
  } else {
    outSegs.push({
      key: 'hk-stale', kind: 'stale', watts: 0,
      label: 'HK stale', sub: 'loads not balanced',
    })
  }
  if (batCharge > 0.01) outSegs.push({
    key: 'bat-chg', kind: 'surplus', watts: batCharge,
    label: `BAT +${batCharge.toFixed(2)} W`, sub: 'charging',
  })

  const inTotal  = inSegs.reduce((a, s) => a + s.watts, 0)
  const outTotal = outSegs.reduce((a, s) => a + s.watts, 0)
  const scale = Math.max(inTotal, outTotal, 0.01)

  const source = pAc > 0.01 ? `AC ${pAc.toFixed(2)} W`
    : psin > 0.01 ? `solar ${psin.toFixed(2)} W`
    : batDischarge > 0.01 ? `battery ${batDischarge.toFixed(2)} W`
    : 'none'
  const loadTitle = loadsCoherent
    ? 'Σ P3V3 + P5V0 + POUT1..6 + PBRN1..2 (derived)'
    : 'HK load fields are not from the same timestamp as bus/battery fields'
  const batteryText = batCharge > 0.01 ? `+${batCharge.toFixed(2)} W`
    : batDischarge > 0.01 ? `${batDischarge.toFixed(2)} W`
    : '—'
  const batteryTitle = batInput.derivedFromLoads
    ? `Load-derived battery source; V_BAT × -I_BAT = ${batInput.measuredWatts.toFixed(2)} W`
    : 'Battery power from V_BAT × I_BAT sign'

  return (
    <div className="card" data-component="PowerBalance">
      <div className="card-head">
        <div className="card-head-left">
          <span className="card-title">Power Balance</span>
        </div>
        <div className={eta !== null && eta > 0.3 ? 'dot success' : 'dot neutral'}
             title="η = Σ useful rails / P_BUS (derived)">
          <span className="sh"></span>
          <span className="lbl"><span className="derived">η {eta !== null ? `${Math.round(eta * 100)}%` : '—'}</span></span>
        </div>
      </div>
      <div className="pb-body">

        <div className="pb-row">
          <div>
            <span className="label">Power in</span>
            <span className="sub-label">solar · AC · bat</span>
          </div>
          <div className="pb-track">
            {inSegs.map((s) => (
              <span key={s.key} className={`pb-seg ${s.kind}`} style={{ width: `${(s.watts / scale) * 100}%` }}
                    title={s.sub ? `${s.label} — ${s.sub}` : s.label}>
                {s.label && (
                  <span className="pb-seg-lines">
                    <span className={`main ${s.kind === 'ac' ? 'derived' : ''}`.trim()}>{s.label}</span>
                    {s.sub && <span className="sub">{s.sub}</span>}
                  </span>
                )}
              </span>
            ))}
          </div>
          <span className="total">{inTotal.toFixed(2)} W</span>
        </div>

        <div className="pb-arrow" aria-hidden="true"><span className="glyph">▼</span></div>

        <div className="pb-row">
          <div>
            <span className="label">Power out</span>
            <span className="sub-label">HK loads · charge</span>
          </div>
          <div className="pb-track">
            {outSegs.map((s) => (
              <span key={s.key} className={`pb-seg ${s.kind}`} style={{ width: `${(s.watts / scale) * 100}%` }}
                    title={s.sub ? `${s.label} — ${s.sub}` : s.label}>
                {s.label && (
                  <span className="pb-seg-lines">
                    <span className="main">{s.label}</span>
                    {s.sub && <span className="sub">{s.sub}</span>}
                  </span>
                )}
              </span>
            ))}
          </div>
          <span className="total">{outTotal.toFixed(2)} W</span>
        </div>

        <div className="pb-status">
          <span className="kv"><span className="k">source</span><span className="v">{source}</span></span>
          <span className="kv"><span className="k">battery</span>
            <span className={`v ${batInput.derivedFromLoads ? 'warn derived' : ''}`.trim()} title={batteryTitle}>{batteryText}</span></span>
          <span className="kv"><span className="k">loads</span>
            <span className={`v ${loadsCoherent ? 'derived' : 'warn'}`.trim()} title={loadTitle}>{loadsCoherent ? `${knownLoads.toFixed(2)} W` : 'stale'}</span></span>
          <span className="kv"><span className="k">EPS board</span>
            <span className="v muted derived" title="P_BUS − Σ measured loads − battery charge (derived residual)">{loadsCoherent ? `${epsBoard.toFixed(2)} W` : '—'}</span></span>
        </div>

      </div>
    </div>
  )
}

export const PowerBalanceCard = memo(PowerBalanceCardInner)
