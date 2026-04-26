// Shared types for the GNC plugin. Mirrors the backend
// DecodedRegister shape from gnc_registers.py.

export interface StatBitfield {
  MODE: number
  MODE_NAME: string
  HERR: boolean
  SERR: boolean
  WDT: boolean
  UV: boolean
  OC: boolean
  OT: boolean
  GNSS_OC: boolean
  GNSS_UP_TO_DATE: boolean
  TLE: boolean
  DES: boolean
  SUN: boolean
  TGL: boolean
  TUMB: boolean
  AME: boolean
  CUSSV: boolean
  EKF: boolean
  byte2_raw: number
}

export interface ActErrBitfield {
  MTQ0: boolean
  MTQ1: boolean
  MTQ2: boolean
  CMG0: boolean
  CMG1: boolean
  CMG2: boolean
  CMG3: boolean
  byte2_raw: number
  byte3_raw: number
}

export interface SenErrBitfield {
  FSS0: boolean; FSS1: boolean; FSS2: boolean
  FSS3: boolean; FSS4: boolean; FSS5: boolean
  MAG0: boolean; MAG1: boolean; MAG2: boolean
  MAG3: boolean; MAG4: boolean; MAG5: boolean
  IMU0: boolean; IMU1: boolean; IMU2: boolean; IMU3: boolean
  STR0: boolean; STR1: boolean
}

export interface TimeBCD {
  hour: number
  minute: number
  second: number
  display: string
}

export interface DateBCD {
  year_yy: number
  year: number
  month: number
  day: number
  weekday: number
  display: string
}

export interface AdcsTmp {
  brdtmp: number
  celsius: number | null
  comm_fault: boolean
}

export interface NvgStatus {
  status: number
  label: string
}

export interface GncMode {
  mode: number
  mode_name: string
}

export interface GncCounters {
  reboot: number
  detumble: number
  sunspin: number
  unexpected_safe: number
}

export interface NvgSensor {
  sensor_id: number
  sensor_name: string
  display: string
  unit: string
  status: number
  timestamp: number | null
  fields: string[]
  values: (number | string)[]
  values_by_field: Record<string, number | string> | null
}

export type RegisterValue =
  | StatBitfield
  | ActErrBitfield
  | SenErrBitfield
  | TimeBCD
  | DateBCD
  | AdcsTmp
  | NvgStatus
  | NvgSensor
  | GncMode
  | GncCounters
  | number[]
  | number
  | string
  | null

/**
 * Local view model used by the GNC card components. GNCPage projects
 * the platform ParametersProvider's `{ v, t }` parameter entries into
 * this `{ value, t }` shape so the cards keep a stable prop signature.
 * `value` is typed against the `RegisterValue` discriminated union so
 * shape-dispatch helpers (formatValue, type-guards) stay type-safe.
 */
export interface RegisterSnapshot {
  value: RegisterValue
  /** Server-anchored Unix ms used for staleness calculations
   *  (age = Date.now() - t). Mirrors the platform parameter `t`. */
  t: number
}

/** Keyed by register name: "STAT", "TIME", "MTQ_USER", etc. */
export type GncState = Record<string, RegisterSnapshot>

/** Local view-model row for the Registers table. Built in GNCPage by
 *  projecting the parameter spec list — `module` / `register` map to
 *  `tags.module` / `tags.register` and are null for canonical keys
 *  that aren't addressable spacecraft registers (handler-emitted
 *  GNC_MODE / GNC_COUNTERS, beacon-only GYRO_RATE_SRC / MAG_SRC /
 *  heartbeats). The Registers table filters those out via
 *  `module !== null` so the register list stays register-only. */
export interface CatalogEntry {
  module: number | null
  register: number | null
  name: string
  type: string
  unit: string
  notes: string
}
