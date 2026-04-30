import { useMemo, useState } from 'react'
import './styles.css'
import { useEpsLive } from './useEpsLive'
import { alarmState, batterySourceActive, socFromVbat, thermalEta } from './derive'
import type { AlarmLevel, EpsFieldName } from './types'
import { useNowMs } from '@/hooks/useNowMs'

import { Cadence, type CadenceChip } from './live/Cadence'
import { HeroCardBus }       from './live/HeroCardBus'
import { HeroCardBat }       from './live/HeroCardBat'
import { HeroCardSys }       from './live/HeroCardSys'
import { HeroCardThermal }   from './live/HeroCardThermal'
import { SolarCard }         from './live/SolarCard'
import { RailsCard }         from './live/RailsCard'
import { VoutStrip }         from './live/VoutStrip'
import { BurnCard }          from './live/BurnCard'
import { PowerBalanceCard }  from './live/PowerBalanceCard'
import { FieldsPane }        from './FieldsPane'

type Subtab = 'live' | 'fields'

const BEACON_KEYS: readonly EpsFieldName[] = [
  'V_BUS', 'I_BUS', 'V_BAT', 'I_BAT', 'V_SYS', 'T_DIE', 'TS_ADC',
]
const HK_ONLY_KEYS: readonly EpsFieldName[] = [
  'V_AC1', 'V_AC2',
  'V3V3', 'I3V3', 'P3V3', 'V5V0', 'I5V0', 'P5V0',
  'VOUT1','IOUT1','POUT1','VOUT2','IOUT2','POUT2','VOUT3','IOUT3','POUT3',
  'VOUT4','IOUT4','POUT4','VOUT5','IOUT5','POUT5','VOUT6','IOUT6','POUT6',
  'VBRN1','IBRN1','PBRN1','VBRN2','IBRN2','PBRN2',
  'VSIN1','ISIN1','PSIN1','VSIN2','ISIN2','PSIN2','VSIN3','ISIN3','PSIN3',
]

function readSubtabFromUrl(): Subtab {
  const params = new URLSearchParams(window.location.search)
  return params.get('tab') === 'fields' ? 'fields' : 'live'
}

function pick(fields: Partial<Record<EpsFieldName, number>>, k: EpsFieldName): number {
  const v = fields[k]
  return typeof v === 'number' ? v : NaN
}

function newestT(
  field_t: Partial<Record<EpsFieldName, number>>,
  keys: readonly EpsFieldName[],
): number | null {
  let newest = -Infinity
  for (const k of keys) {
    const t = field_t[k]
    if (typeof t === 'number' && t > newest) newest = t
  }
  return Number.isFinite(newest) ? newest : null
}

export default function EpsPage() {
  const [tab, setTab] = useState<Subtab>(readSubtabFromUrl)
  const nowMs = useNowMs()

  const {
    fields, field_t, prev_fields, prev_field_t,
    chargeDir, latched, acknowledgeLatch,
    epsMode, epsHeartbeat,
  } = useEpsLive()

  const hasAny = Object.keys(fields).length > 0

  const alarms = useMemo(() => hasAny ? alarmState(fields) : {}, [fields, hasAny])
  const soc    = useMemo(() => {
    const v = fields.V_BAT
    return typeof v === 'number' ? socFromVbat(v) : null
  }, [fields])
  const eta    = useMemo(() => {
    const tCur  = field_t.T_DIE
    const tPrev = prev_field_t.T_DIE
    if (tCur === undefined || tPrev === undefined) return null
    const td     = fields.T_DIE
    const tdPrev = prev_fields.T_DIE
    if (typeof td !== 'number' || typeof tdPrev !== 'number') return null
    return thermalEta(td, tdPrev, tCur - tPrev, 60)
  }, [fields.T_DIE, prev_fields.T_DIE, field_t.T_DIE, prev_field_t.T_DIE])
  const displayChargeDir = useMemo(() => (
    batterySourceActive(fields) ? 'discharge' : chargeDir
  ), [fields, chargeDir])

  const beaconT = useMemo(() => newestT(field_t, BEACON_KEYS), [field_t])
  const hkT     = useMemo(() => newestT(field_t, HK_ONLY_KEYS), [field_t])

  const beaconChips: CadenceChip[] = useMemo(() => {
    const chips: CadenceChip[] = []
    if (epsMode !== null) {
      chips.push({ label: `MODE · ${epsMode}`, variant: 'info', title: 'eps_mode raw (FSW enum pending)' })
    }
    if (epsHeartbeat !== null) {
      const hb = epsHeartbeat === 1 ? 'OK' : epsHeartbeat === 0 ? 'DEAD' : '?'
      const variant = epsHeartbeat === 1 ? 'hb-ok'
        : epsHeartbeat === 0 ? 'hb-dead'
        : 'hb-unk'
      chips.push({ label: `HB · ${hb}`, variant, title: `eps_heartbeat = ${epsHeartbeat}` })
    }
    return chips
  }, [epsMode, epsHeartbeat])

  const onTabChange = (next: Subtab) => {
    setTab(next)
    const url = new URL(window.location.href)
    if (next === 'live') url.searchParams.delete('tab')
    else url.searchParams.set('tab', next)
    window.history.replaceState({}, '', url.toString())
  }

  return (
    <div className="eps-page">
      <nav className="subtabs" role="tablist">
        <button role="tab" aria-selected={tab === 'live'}
                className={`subtab ${tab === 'live' ? 'active' : ''}`}
                onClick={() => onTabChange('live')}>
          Overview
        </button>
        <button role="tab" aria-selected={tab === 'fields'}
                className={`subtab ${tab === 'fields' ? 'active' : ''}`}
                onClick={() => onTabChange('fields')}>
          Fields
        </button>
      </nav>

      <div className="body">
        <section id="pane-live" className={`pane ${tab === 'live' ? 'active' : ''}`}>

          <Cadence kind="beacon" latestT={beaconT} nowMs={nowMs} chips={beaconChips} />

          <div className="hero-row">
            <HeroCardBus
              V_BUS={pick(fields, 'V_BUS')} I_BUS={pick(fields, 'I_BUS')}
              prev_V_BUS={pick(prev_fields, 'V_BUS')}
              alarm={alarms.V_BUS as AlarmLevel ?? 'unknown'}
            />
            <HeroCardBat
              V_BAT={pick(fields, 'V_BAT')} I_BAT={pick(fields, 'I_BAT')}
              prev_V_BAT={pick(prev_fields, 'V_BAT')}
              chargeDir={displayChargeDir} soc={soc}
              alarm={alarms.V_BAT as AlarmLevel ?? 'unknown'}
            />
            <HeroCardSys
              V_SYS={pick(fields, 'V_SYS')}
              prev_V_SYS={pick(prev_fields, 'V_SYS')}
              alarm={alarms.V_SYS as AlarmLevel ?? 'unknown'}
            />
            <HeroCardThermal
              T_DIE={pick(fields, 'T_DIE')} TS_ADC={pick(fields, 'TS_ADC')}
              prev_T_DIE={pick(prev_fields, 'T_DIE')}
              etaSeconds={eta}
              alarm={alarms.T_DIE as AlarmLevel ?? 'unknown'}
            />
          </div>

          <Cadence kind="hk" latestT={hkT} nowMs={nowMs} />

          <div className="output-row">
            <SolarCard fields={fields} />
            <RailsCard
              V3V3={pick(fields, 'V3V3')} I3V3={pick(fields, 'I3V3')} P3V3={pick(fields, 'P3V3')}
              V5V0={pick(fields, 'V5V0')} I5V0={pick(fields, 'I5V0')} P5V0={pick(fields, 'P5V0')}
            />
            <VoutStrip fields={fields} />
            <BurnCard
              VBRN1={pick(fields, 'VBRN1')} IBRN1={pick(fields, 'IBRN1')} PBRN1={pick(fields, 'PBRN1')}
              VBRN2={pick(fields, 'VBRN2')} IBRN2={pick(fields, 'IBRN2')} PBRN2={pick(fields, 'PBRN2')}
              latched={latched} onAcknowledge={acknowledgeLatch}
            />
          </div>

          <PowerBalanceCard fields={fields} field_t={field_t} />

        </section>

        <section id="pane-fields" className={`pane ${tab === 'fields' ? 'active' : ''}`}>
          <FieldsPane fields={fields} field_t={field_t} />
        </section>
      </div>
    </div>
  )
}
