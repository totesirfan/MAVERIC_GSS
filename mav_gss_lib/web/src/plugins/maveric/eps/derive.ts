import type { AlarmLevel, ChargeDir, EpsFieldName, EpsFields, SourceId } from './types'

const isFiniteNumber = (v: unknown): v is number =>
  typeof v === 'number' && Number.isFinite(v)

export function fmt(v: number | null | undefined, digits: number): string {
  if (!isFiniteNumber(v)) return '—'
  return v.toFixed(digits)
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v))
}

export function socFromVbat(v: number | null | undefined): number | null {
  if (!isFiniteNumber(v)) return null
  return clamp(((v - 6.0) / 2.4) * 100, 0, 100)
}

const SOURCE_PRIORITY: readonly SourceId[] = ['V_AC2', 'V_AC1', 'VSIN1', 'VSIN2', 'VSIN3', 'BAT']
const SOURCE_VOLTAGE_THRESHOLD = 1.0
const SOURCE_POWER_THRESHOLD_W = 0.05
const BAT_DISCHARGE_THRESHOLD = -0.010
const BUS_LOAD_MISMATCH_TOLERANCE_W = 0.25

export function activeSource(fields: EpsFields | Partial<EpsFields> | null | undefined): SourceId | null {
  if (!fields) return null
  for (const id of SOURCE_PRIORITY) {
    if (id === 'BAT') {
      const i = (fields as Partial<EpsFields>).I_BAT
      if (isFiniteNumber(i) && i < BAT_DISCHARGE_THRESHOLD) return 'BAT'
      if (batterySourceActive(fields)) return 'BAT'
      continue
    }
    const v = (fields as Partial<EpsFields>)[id]
    if (isFiniteNumber(v) && v > SOURCE_VOLTAGE_THRESHOLD) return id
  }
  return null
}

const CHARGE_DEADBAND = 0.05
const CHARGE_HYSTERESIS = 0.010

export function chargeDirection(current: number, recent: readonly number[]): ChargeDir {
  if (!isFiniteNumber(current)) return 'idle'
  if (Math.abs(current) > CHARGE_DEADBAND) {
    return current > 0 ? 'charge' : 'discharge'
  }
  if (recent.length < 2) return 'idle'
  const samples = [...recent, current].slice(-3)
  if (samples.length < 3) return 'idle'
  const allFinite = samples.every(isFiniteNumber)
  if (!allFinite) return 'idle'
  const allAboveHysteresis = samples.every((s) => Math.abs(s) > CHARGE_HYSTERESIS)
  if (!allAboveHysteresis) return 'idle'
  const allPositive = samples.every((s) => s > 0)
  const allNegative = samples.every((s) => s < 0)
  if (allPositive) return 'charge'
  if (allNegative) return 'discharge'
  return 'idle'
}

export function thermalEta(
  T: number,
  prevT: number,
  dtMs: number,
  limit: number,
): number | null {
  if (!isFiniteNumber(T) || !isFiniteNumber(prevT) || !isFiniteNumber(dtMs) || !isFiniteNumber(limit)) {
    return null
  }
  if (dtMs < 1000) return null
  const ratePerSec = ((T - prevT) * 1000) / dtMs
  if (Math.abs(ratePerSec) < 0.02) return null
  return (limit - T) / ratePerSec
}

export function efficiency(
  fields: EpsFields | Partial<EpsFields> | null | undefined,
  _source: SourceId | null,
): number | null {
  if (!fields) return null
  const f = fields as Partial<EpsFields>
  const { V_BUS, I_BUS } = f
  if (!isFiniteNumber(V_BUS) || !isFiniteNumber(I_BUS)) return null
  const pBus = V_BUS * I_BUS
  if (pBus < 0.1) return null
  const useful = measuredLoadPower(f)
  if (useful > pBus + BUS_LOAD_MISMATCH_TOLERANCE_W) return null
  const ratio = useful / pBus
  if (!Number.isFinite(ratio)) return null
  return Math.max(0, Math.min(1, ratio))
}

const V_BAT_CAUTION = 6.8
const V_BAT_DANGER = 6.0

const V_BUS_LOW_DANGER = 6.5
const V_BUS_HIGH_DANGER = 9.5

const V_SYS_BROWNOUT_DANGER = 5.5
const V_SYS_LOW_CAUTION = 6.5
const V_SYS_HIGH_CAUTION = 8.5

const T_DIE_JUNCTION_DANGER = 85
const T_DIE_OVERHEAT_DANGER = 60
const T_DIE_COLD_CAUTION = 0
const T_DIE_COLD_DANGER = -10

const I_BUS_CAUTION = 2.0

const VBRN_DANGER = 0.1

const V3V3_NOM = 3.3
const V5V0_NOM = 5.0
const RAIL_DEV_CAUTION = 0.05

function railAlarm(v: unknown, nom: number): AlarmLevel {
  if (!isFiniteNumber(v)) return 'unknown'
  if (v <= 0) return 'danger'
  const dev = Math.abs(v - nom) / nom
  return dev > RAIL_DEV_CAUTION ? 'caution' : 'ok'
}

export function alarmState(
  fields: EpsFields | Partial<EpsFields> | Record<string, unknown>,
): Record<string, AlarmLevel> {
  const out: Record<string, AlarmLevel> = {}
  const f = fields as Record<string, unknown>

  if ('V_BUS' in f) {
    const v = f.V_BUS
    if (!isFiniteNumber(v)) out.V_BUS = 'unknown'
    else if (v < V_BUS_LOW_DANGER || v > V_BUS_HIGH_DANGER) out.V_BUS = 'danger'
    else out.V_BUS = 'ok'
  }

  if ('V_BAT' in f) {
    const v = f.V_BAT
    if (!isFiniteNumber(v)) out.V_BAT = 'unknown'
    else if (v < V_BAT_DANGER) out.V_BAT = 'danger'
    else if (v < V_BAT_CAUTION) out.V_BAT = 'caution'
    else out.V_BAT = 'ok'
  }

  if ('V_SYS' in f) {
    const v = f.V_SYS
    if (!isFiniteNumber(v) || v <= 0) out.V_SYS = 'unknown'
    else if (v < V_SYS_BROWNOUT_DANGER) out.V_SYS = 'danger'
    else if (v < V_SYS_LOW_CAUTION || v > V_SYS_HIGH_CAUTION) out.V_SYS = 'caution'
    else out.V_SYS = 'ok'
  }

  if ('T_DIE' in f) {
    const v = f.T_DIE
    if (!isFiniteNumber(v)) out.T_DIE = 'unknown'
    else if (v >= T_DIE_JUNCTION_DANGER) out.T_DIE = 'danger'
    else if (v < T_DIE_COLD_DANGER) out.T_DIE = 'danger'
    else if (v > T_DIE_OVERHEAT_DANGER) out.T_DIE = 'danger'
    else if (v < T_DIE_COLD_CAUTION) out.T_DIE = 'caution'
    else out.T_DIE = 'ok'
  }

  if ('I_BUS' in f) {
    const v = f.I_BUS
    if (!isFiniteNumber(v)) out.I_BUS = 'unknown'
    else if (v > I_BUS_CAUTION) out.I_BUS = 'caution'
    else out.I_BUS = 'ok'
  }

  if ('VBRN1' in f) {
    const v = f.VBRN1
    if (!isFiniteNumber(v)) out.VBRN1 = 'unknown'
    else if (v > VBRN_DANGER) out.VBRN1 = 'danger'
    else out.VBRN1 = 'ok'
  }

  if ('VBRN2' in f) {
    const v = f.VBRN2
    if (!isFiniteNumber(v)) out.VBRN2 = 'unknown'
    else if (v > VBRN_DANGER) out.VBRN2 = 'danger'
    else out.VBRN2 = 'ok'
  }

  if ('V3V3' in f) out.V3V3 = railAlarm(f.V3V3, V3V3_NOM)
  if ('V5V0' in f) out.V5V0 = railAlarm(f.V5V0, V5V0_NOM)

  return out
}

/**
 * Classify a solar panel's state via sibling comparison.
 *   GEN   — PSINn ≥ 100 mW (actively producing).
 *   DEAD  — a sibling is GEN AND VSINn < 0.5 V AND PSINn < 10 mW.
 *           Rationale: a shaded-but-healthy panel still shows open-circuit
 *           voltage (~2–3 V); only a broken panel reads dark. The sibling
 *           check prevents false-DEAD during eclipse when everyone is quiet.
 *   IDLE  — otherwise (eclipse, partial shadow, or uncertain).
 */
export type SolarPanelState = 'gen' | 'idle' | 'dead'

const SOLAR_ACTIVE_W = 0.10
const SOLAR_DEAD_V = 0.5
const SOLAR_DEAD_W = 0.01

export function classifySolarPanel(
  fields: Partial<EpsFields>,
  n: 1 | 2 | 3,
): SolarPanelState {
  const pKey = `PSIN${n}` as keyof EpsFields
  const vKey = `VSIN${n}` as keyof EpsFields
  const psin = fields[pKey]
  const vsin = fields[vKey]
  const p = isFiniteNumber(psin) ? psin : 0
  const v = isFiniteNumber(vsin) ? vsin : 0
  if (p >= SOLAR_ACTIVE_W) return 'gen'
  const others: Array<1 | 2 | 3> = ([1, 2, 3] as const).filter((k) => k !== n)
  const anySiblingGen = others.some((k) => {
    const s = fields[`PSIN${k}` as keyof EpsFields]
    return isFiniteNumber(s) && s >= SOLAR_ACTIVE_W
  })
  if (anySiblingGen && v < SOLAR_DEAD_V && p < SOLAR_DEAD_W) return 'dead'
  return 'idle'
}

/**
 * Freshness tiers for Cadence captions. Thresholds match GNC (30 min / 12 h)
 * — pass-cadence calibrated, not tight-seconds.
 */
export type Freshness = 'fresh' | 'stale' | 'expired' | 'empty'

const FRESH_CUTOFF_MS = 30 * 60 * 1000
const STALE_CUTOFF_MS = 12 * 60 * 60 * 1000

export function classifyFreshness(
  t: number | null | undefined,
  now: number,
): Freshness {
  if (!isFiniteNumber(t)) return 'empty'
  const age = now - t
  if (age < FRESH_CUTOFF_MS) return 'fresh'
  if (age < STALE_CUTOFF_MS) return 'stale'
  return 'expired'
}

/** Format a ms age as "N s" / "N min" / "N h" / "N d". */
export function formatAge(ageMs: number | null | undefined): string {
  if (!isFiniteNumber(ageMs) || ageMs < 0) return '—'
  const s = Math.floor(ageMs / 1000)
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  if (h < 48) return `${h} h`
  return `${Math.floor(h / 24)} d`
}

/**
 * Measured output loads that are reported directly by EPS HK.
 * Battery charging is intentionally excluded; it is handled as its own sink.
 * Negative load powers are treated as sensor noise, not load generation.
 */
export const MEASURED_LOAD_KEYS: readonly EpsFieldName[] = [
  'P3V3', 'P5V0',
  'POUT1', 'POUT2', 'POUT3', 'POUT4', 'POUT5', 'POUT6',
  'PBRN1', 'PBRN2',
]

export function measuredLoadPower(
  fields: EpsFields | Partial<EpsFields> | null | undefined,
): number {
  if (!fields) return 0
  const f = fields as Partial<EpsFields>
  let total = 0
  for (const k of MEASURED_LOAD_KEYS) {
    const v = f[k]
    if (isFiniteNumber(v) && v > 0) total += v
  }
  return total
}

export function batteryChargePower(
  fields: EpsFields | Partial<EpsFields> | null | undefined,
): number {
  if (!fields) return 0
  const { V_BAT, I_BAT } = fields as Partial<EpsFields>
  if (!isFiniteNumber(V_BAT) || !isFiniteNumber(I_BAT) || V_BAT <= 0 || I_BAT <= 0) return 0
  return V_BAT * I_BAT
}

export function batteryDischargePower(
  fields: EpsFields | Partial<EpsFields> | null | undefined,
): number {
  if (!fields) return 0
  const { V_BAT, I_BAT } = fields as Partial<EpsFields>
  if (!isFiniteNumber(V_BAT) || !isFiniteNumber(I_BAT) || V_BAT <= 0 || I_BAT >= 0) return 0
  return V_BAT * -I_BAT
}

export function busPower(
  fields: EpsFields | Partial<EpsFields> | null | undefined,
): number | null {
  if (!fields) return null
  const { V_BUS, I_BUS } = fields as Partial<EpsFields>
  if (!isFiniteNumber(V_BUS) || !isFiniteNumber(I_BUS)) return null
  const pBus = V_BUS * I_BUS
  return Math.max(0, pBus)
}

function positivePower(v: number | null | undefined): number {
  return isFiniteNumber(v) && v > 0 ? v : 0
}

function solarInputPower(fields: Partial<EpsFields>): number {
  return positivePower(fields.PSIN1) + positivePower(fields.PSIN2) + positivePower(fields.PSIN3)
}

function externalSourcePresent(fields: Partial<EpsFields>): boolean {
  if (isFiniteNumber(fields.V_AC1) && fields.V_AC1 > SOURCE_VOLTAGE_THRESHOLD) return true
  if (isFiniteNumber(fields.V_AC2) && fields.V_AC2 > SOURCE_VOLTAGE_THRESHOLD) return true
  if (solarInputPower(fields) > SOURCE_POWER_THRESHOLD_W) return true
  return false
}

export function batterySourceActive(
  fields: EpsFields | Partial<EpsFields> | null | undefined,
): boolean {
  if (!fields) return false
  const f = fields as Partial<EpsFields>
  if (!isFiniteNumber(f.V_BAT) || f.V_BAT <= SOURCE_VOLTAGE_THRESHOLD) return false
  if (isFiniteNumber(f.I_BAT) && f.I_BAT < BAT_DISCHARGE_THRESHOLD) return true
  if (externalSourcePresent(f)) return false

  const pBus = busPower(f)
  const sysPowered = isFiniteNumber(f.V_SYS) && f.V_SYS > SOURCE_VOLTAGE_THRESHOLD
  const hasMeasuredLoads = measuredLoadPower(f) > SOURCE_POWER_THRESHOLD_W
  const busSensorAtZero = pBus !== null && pBus <= SOURCE_POWER_THRESHOLD_W

  return sysPowered || hasMeasuredLoads || busSensorAtZero
}

export interface BatteryInputPower {
  watts: number
  measuredWatts: number
  derivedFromLoads: boolean
}

/**
 * Battery current is useful for direction, but on battery-only bench/HK data it
 * can be much smaller than the measured output rails. In that mode, use the HK
 * load sum as the displayed source power and keep the raw VBAT*IBAT value as a
 * diagnostic instead of drawing an impossible balance.
 */
export function batteryInputPower(
  fields: EpsFields | Partial<EpsFields> | null | undefined,
  requiredSinkPower = 0,
): BatteryInputPower {
  const measuredWatts = batteryDischargePower(fields)
  if (!fields) return { watts: 0, measuredWatts, derivedFromLoads: false }

  const f = fields as Partial<EpsFields>
  const required = isFiniteNumber(requiredSinkPower) ? Math.max(0, requiredSinkPower) : 0
  const pBus = busPower(fields)
  const vBatPresent = isFiniteNumber(f.V_BAT) && f.V_BAT > SOURCE_VOLTAGE_THRESHOLD
  const batteryOnlyLoads = vBatPresent
    && !externalSourcePresent(f)
    && pBus !== null
    && pBus <= SOURCE_POWER_THRESHOLD_W
    && required > SOURCE_POWER_THRESHOLD_W

  if (batteryOnlyLoads && required > measuredWatts + SOURCE_POWER_THRESHOLD_W) {
    return { watts: required, measuredWatts, derivedFromLoads: true }
  }

  return { watts: measuredWatts, measuredWatts, derivedFromLoads: false }
}

/**
 * Residual EPS board/quiescent draw after direct loads and battery charge.
 * P_BUS is treated as the bus demand reported by EPS, including charging
 * current when the battery charger is active.
 */
export function deriveEpsBoardPower(
  fields: EpsFields | Partial<EpsFields> | null | undefined,
): number | null {
  if (!fields) return null
  const pBus = busPower(fields)
  if (pBus === null) return null
  return Math.max(0, pBus - measuredLoadPower(fields) - batteryChargePower(fields))
}

/**
 * Derive AC input power via energy conservation on the bus node.
 *   P_BUS = ΣPSIN + P_AC + P_bat_discharge
 * Rearranged: P_AC = P_BUS − ΣPSIN − P_bat_discharge
 *
 * Discharge (I_BAT<0): battery adds to sources → subtract from P_BUS.
 * Charge   (I_BAT>0): battery is a sink already included in P_BUS, so it
 *                      must not be added into the source residual again.
 *
 * Returns null when V_BUS / I_BUS are not measured yet.
 */
export function derivePAC(
  fields: EpsFields | Partial<EpsFields> | null | undefined,
): number | null {
  if (!fields) return null
  const { V_BUS, I_BUS, PSIN1, PSIN2, PSIN3 } = fields as Partial<EpsFields>
  if (!isFiniteNumber(V_BUS) || !isFiniteNumber(I_BUS)) return null
  const pBus = V_BUS * I_BUS
  const pSin = (isFiniteNumber(PSIN1) ? PSIN1 : 0)
    + (isFiniteNumber(PSIN2) ? PSIN2 : 0)
    + (isFiniteNumber(PSIN3) ? PSIN3 : 0)
  return pBus - pSin - batteryDischargePower(fields)
}

/**
 * Format a current in amps as `NN mA` (below 1 A) or `X.XX A` (at or above 1 A).
 * Negative values render with U+2212 to match the codebase convention.
 */
export function formatCurrent(a: number | null | undefined): string {
  if (!isFiniteNumber(a)) return '—'
  const abs = Math.abs(a)
  if (abs < 1.0) {
    const mA = Math.round(a * 1000)
    if (mA < 0) return `−${-mA} mA`
    return `${mA} mA`
  }
  if (a < 0) return `−${Math.abs(a).toFixed(2)} A`
  return `${a.toFixed(2)} A`
}
