import type { AdcsTmp, NvgSensor, RegisterSnapshot } from '../types'

export function asFloatVec(
  snap: RegisterSnapshot | undefined,
  length: number,
): number[] | null {
  const v = snap?.value
  return Array.isArray(v) && v.length === length && v.every(n => typeof n === 'number')
    ? (v as number[])
    : null
}

export const qFrom    = (s?: RegisterSnapshot) => asFloatVec(s, 4)
export const rateFrom = (s?: RegisterSnapshot) => asFloatVec(s, 3)
export const mtqFrom  = (s?: RegisterSnapshot) => asFloatVec(s, 3)
export const magFrom  = (s?: RegisterSnapshot) => asFloatVec(s, 3)

export function isAdcsTmp(v: unknown): v is AdcsTmp {
  return !!v && typeof v === 'object'
    && 'celsius' in v
    && 'comm_fault' in v
    && 'brdtmp' in v
}

export function adcsTmpFrom(snap: RegisterSnapshot | undefined): AdcsTmp | null {
  const v = snap?.value
  if (isAdcsTmp(v)) return v as AdcsTmp
  // tlm_beacon emits ADCS_TMP as a plain f32 (degrees C); int16[2] from
  // mtq_get_1 reg 148 still arrives as the structured AdcsTmp object via
  // its calibrator. Accept the bare number for the beacon path.
  if (typeof v === 'number' && Number.isFinite(v)) {
    return { celsius: v, comm_fault: false, brdtmp: 0 } as AdcsTmp
  }
  return null
}

export function isNvgSensor(v: unknown): v is NvgSensor {
  return !!v && typeof v === 'object'
    && 'sensor_id' in v
    && 'values' in v
}

export function nvgSensorFrom(snap: RegisterSnapshot | undefined): NvgSensor | null {
  return isNvgSensor(snap?.value) ? (snap!.value as NvgSensor) : null
}

// _coerce_float in nvg_sensors.py returns the raw token (string) when a
// numeric parse fails, so a mixed array is possible from the wire. Drop
// non-numeric entries to null at the consumption site rather than
// crashing on toFixed.
export function nvgNumericValues(sensor: NvgSensor): (number | null)[] {
  return sensor.values.map(v => typeof v === 'number' ? v : null)
}

const SENTINEL_FLOAT = -1e30

export function isRateSentinel(v: number): boolean {
  return v < SENTINEL_FLOAT
}

export function anyRateSentinel(rate: number[] | null): boolean {
  return !!rate && rate.some(isRateSentinel)
}

export function rateMagnitude(rate: number[] | null): number | null {
  if (!rate || anyRateSentinel(rate)) return null
  return Math.hypot(...rate)
}

export function magMagnitude(mag: number[] | null): number | null {
  if (!mag) return null
  return Math.hypot(...mag)
}

// Quaternion derivations — identity-safe axis extraction. Scalar-first
// convention (Q0 is the scalar part) matches the flight-software
// convention in the Apr 17 CSV. Clamps q0 to acos's [-1, 1] domain.
export function deriveThetaAxis(q: number[] | null): {
  theta: number | null
  axis: [number, number, number] | null
  display: string
} {
  if (!q || q.length < 4) return { theta: null, axis: null, display: '—' }
  const q0 = Math.max(-1, Math.min(1, q[0]))
  const theta = 2 * Math.acos(q0)
  const half = Math.sin(theta / 2)
  if (half < 1e-6) {
    return { theta: 0, axis: null, display: '0° · (identity)' }
  }
  const axis: [number, number, number] = [q[1] / half, q[2] / half, q[3] / half]
  const deg = theta * 180 / Math.PI
  return {
    theta,
    axis,
    display: `${deg.toFixed(2)}° · (${axis.map(v => v.toFixed(3)).join(', ')})`,
  }
}

// Quaternion → ZYX intrinsic Euler (yaw, pitch, roll) in degrees.
// Assumes unit quaternion in scalar-first form [q0, q1, q2, q3].
export function quatToYpr(q: number[] | null): [number, number, number] | null {
  if (!q || q.length < 4) return null
  const [w, x, y, z] = q
  const sinp = 2 * (w * y - z * x)
  const pitch = Math.abs(sinp) >= 1 ? Math.sign(sinp) * Math.PI / 2 : Math.asin(sinp)
  const yaw = Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
  const roll = Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
  const r2d = 180 / Math.PI
  return [yaw * r2d, pitch * r2d, roll * r2d]
}
