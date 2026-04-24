import type { AlarmLevel, ChargeDir, EpsFields, SourceId } from './types'

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
const BAT_DISCHARGE_THRESHOLD = -0.010

export function activeSource(fields: EpsFields | Partial<EpsFields> | null | undefined): SourceId | null {
  if (!fields) return null
  for (const id of SOURCE_PRIORITY) {
    if (id === 'BAT') {
      const i = (fields as Partial<EpsFields>).I_BAT
      if (isFiniteNumber(i) && i < BAT_DISCHARGE_THRESHOLD) return 'BAT'
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
  const usefulKeys: ReadonlyArray<keyof EpsFields> = [
    'P3V3', 'P5V0',
    'POUT1', 'POUT2', 'POUT3', 'POUT4', 'POUT5', 'POUT6',
    'PBRN1', 'PBRN2',
  ]
  let useful = 0
  for (const k of usefulKeys) {
    const v = f[k]
    if (isFiniteNumber(v)) useful += v
  }
  const ratio = useful / pBus
  if (!Number.isFinite(ratio)) return null
  return Math.max(0, Math.min(1, ratio))
}

const V_BAT_CAUTION = 6.8
const V_BAT_DANGER = 6.0

const V_BUS_LOW_DANGER = 6.5
const V_BUS_HIGH_DANGER = 9.5

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
 * Derive AC input power via energy conservation on the bus node.
 *   P_BUS = ΣPSIN + P_AC + P_bat_discharge − P_bat_charge
 * Rearranged: P_AC = P_BUS − ΣPSIN − (V_BAT × −I_BAT)
 *
 * Discharge (I_BAT<0): battery adds to sources → subtract from P_BUS.
 * Charge   (I_BAT>0): battery is a sink → add back.
 *
 * Returns null when V_BUS / I_BUS are not measured yet.
 */
export function derivePAC(
  fields: EpsFields | Partial<EpsFields> | null | undefined,
): number | null {
  if (!fields) return null
  const { V_BUS, I_BUS, V_BAT, I_BAT, PSIN1, PSIN2, PSIN3 } = fields as Partial<EpsFields>
  if (!isFiniteNumber(V_BUS) || !isFiniteNumber(I_BUS)) return null
  const pBus = V_BUS * I_BUS
  const pSin = (isFiniteNumber(PSIN1) ? PSIN1 : 0)
    + (isFiniteNumber(PSIN2) ? PSIN2 : 0)
    + (isFiniteNumber(PSIN3) ? PSIN3 : 0)
  let batTerm = 0
  if (isFiniteNumber(V_BAT) && isFiniteNumber(I_BAT)) {
    batTerm = V_BAT * -I_BAT
  }
  return pBus - pSin - batTerm
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
