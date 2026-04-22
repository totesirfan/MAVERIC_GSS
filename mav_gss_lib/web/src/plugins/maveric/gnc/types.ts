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
 * Live-state entry for one GNC register.
 *
 * Post-v2 this is a thin view model over the platform `TelemetryEntry`:
 *   `value` is projected from `entry.v` (structured `RegisterValue`);
 *   `t` is the server-anchored ingest timestamp used for staleness
 *   calculations (age = Date.now() - t).
 *
 * Transport/debug fields (`raw_tokens`, `decode_ok`, `decode_error`,
 * `gs_ts`, `pkt_num`) are intentionally dropped — the extractor filters
 * decode_ok=False entries before they reach state, and per-packet
 * provenance lives in the RX log, not in canonical state.
 *
 * Static metadata (`name`, `module`, `register`, `type`, `unit`, `notes`)
 * moved to `CatalogEntry` — fetched via
 * `useTelemetryCatalog<CatalogEntry[]>('gnc')` and keyed by register name.
 */
export interface RegisterSnapshot {
  value: RegisterValue
  /** Server-anchored Unix ms — matches the platform TelemetryEntry `t`
   *  field. */
  t: number
}

/** Keyed by register name: "STAT", "TIME", "MTQ_USER", etc. */
export type GncState = Record<string, RegisterSnapshot>

/** One row in the register catalog, served by
 *  GET /api/telemetry/gnc/catalog. Metadata only — live values come
 *  from useTelemetry('gnc'). */
export interface CatalogEntry {
  module: number
  register: number
  name: string
  type: string
  unit: string
  notes: string
}
