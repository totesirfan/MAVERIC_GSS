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
  raw_tokens: string[]
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

export interface RegisterSnapshot {
  name: string
  /** MTQ registers have module numbers; NVG snapshots emit null. */
  module: number | null
  /** MTQ register number; NVG sensor ID; NVG status = null. */
  register: number | null
  type: string
  unit: string
  value: RegisterValue
  raw_tokens: string[]
  decode_ok: boolean
  decode_error: string | null
  /** Server-anchored Unix ms when the satellite's RES was received.
   *  Used for age calculations so values survive MAV_WEB restart with
   *  correct staleness (age = Date.now() - received_at_ms). */
  received_at_ms: number
  /** Ground-station timestamp string attached to the source packet. */
  gs_ts: string
  /** Source packet number for traceability. */
  pkt_num: number
}

/** Keyed by register name: "STAT", "TIME", "MTQ_USER", etc. */
export type GncState = Record<string, RegisterSnapshot>

export interface GncRegisterUpdateMsg {
  type: 'gnc_register_update'
  registers: Record<string, RegisterSnapshot>
}

/** One row in the register catalog, served by GET /api/plugins/gnc/catalog.
 *  Metadata only — live values come from the snapshot hook. */
export interface CatalogEntry {
  module: number
  register: number
  name: string
  type: string
  unit: string
  notes: string
}
