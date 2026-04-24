import { memo, useMemo } from 'react'
import { derivePAC, efficiency } from '../derive'
import type { EpsFieldMap } from '../types'

interface Props {
  fields: EpsFieldMap
}

function finite(v: number | undefined): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : 0
}

interface Segment {
  key: string
  kind: 'solar' | 'solar-aux' | 'solar-idle' | 'ac' | 'vout-on' | 'rail' | 'deficit' | 'surplus'
  watts: number
  label?: string
  sub?: string
}

function PowerBalanceCardInner({ fields }: Props) {
  const pBus = useMemo(() => {
    const v = finite(fields.V_BUS) * finite(fields.I_BUS)
    return v >= 0 ? v : 0
  }, [fields.V_BUS, fields.I_BUS])

  const psin = finite(fields.PSIN1) + finite(fields.PSIN2) + finite(fields.PSIN3)
  const pAc = useMemo(() => derivePAC(fields) ?? 0, [fields])
  const iBat = finite(fields.I_BAT)
  const vBat = finite(fields.V_BAT)
  const batDischarge = iBat < 0 ? vBat * -iBat : 0
  const batCharge    = iBat > 0 ? vBat *  iBat : 0

  const knownLoads = finite(fields.P3V3) + finite(fields.P5V0)
    + finite(fields.POUT1) + finite(fields.POUT2) + finite(fields.POUT3)
    + finite(fields.POUT4) + finite(fields.POUT5) + finite(fields.POUT6)
    + finite(fields.PBRN1) + finite(fields.PBRN2)
  const epsBoard = Math.max(0, pBus - knownLoads)

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
    const vAc = ac2 > 1 ? ac2 : ac1
    const acLabel = ac2 > 1 ? 'AC2' : ac1 > 1 ? 'AC1' : 'AC'
    inSegs.push({
      key: 'ac', kind: 'ac', watts: pAc,
      label: `${acLabel} · ${pAc.toFixed(2)} W`,
      sub: `${vAc.toFixed(2)} V`,
    })
  }
  if (batDischarge > 0.01) inSegs.push({
    key: 'bat-dis', kind: 'deficit', watts: batDischarge,
    label: `BAT ${batDischarge.toFixed(2)} W`, sub: 'covering',
  })

  const outSegs: Segment[] = []
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
  if (finite(fields.P3V3) > 0.01) outSegs.push({
    key: 'p3v3', kind: 'rail', watts: finite(fields.P3V3),
    label: `3V3 ${finite(fields.P3V3).toFixed(2)} W`,
    sub: `${(finite(fields.I3V3) * 1000).toFixed(0)} mA`,
  })
  if (finite(fields.P5V0) > 0.01) outSegs.push({
    key: 'p5v0', kind: 'rail', watts: finite(fields.P5V0),
    label: `5V ${finite(fields.P5V0).toFixed(2)} W`,
  })
  if (epsBoard > 0.01) outSegs.push({
    key: 'eps-board', kind: 'solar-idle', watts: epsBoard,
    label: `EPS board ${epsBoard.toFixed(2)} W`, sub: 'MCU + quiescent',
  })
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
              <span key={s.key} className={`pb-seg ${s.kind}`} style={{ width: `${(s.watts / scale) * 100}%` }}>
                {s.label && (
                  <span className="pb-seg-lines">
                    <span className={s.kind === 'ac' ? 'derived' : ''}>{s.label}</span>
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
            <span className="sub-label">V_BUS · I_BUS</span>
          </div>
          <div className="pb-track">
            {outSegs.map((s) => (
              <span key={s.key} className={`pb-seg ${s.kind}`} style={{ width: `${(s.watts / scale) * 100}%` }}>
                {s.label && (
                  <span className="pb-seg-lines">
                    <span>{s.label}</span>
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
          <span className="kv"><span className="k">loads</span>
            <span className="v derived" title="Σ P3V3 + P5V0 + POUT1..6 + PBRN1..2 (derived)">{knownLoads.toFixed(2)} W</span></span>
          <span className="kv"><span className="k">EPS board</span>
            <span className="v muted derived" title="P_BUS − Σ measured loads (derived residual)">{epsBoard.toFixed(2)} W</span></span>
        </div>

      </div>
    </div>
  )
}

export const PowerBalanceCard = memo(PowerBalanceCardInner)
