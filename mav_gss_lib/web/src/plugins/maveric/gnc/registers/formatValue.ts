import type { RegisterSnapshot, RegisterValue } from '../types'

/** Collapse a decoded register's `value` into one display string suited
 *  for a table cell. Mirrors the backend shape dispatch used by the
 *  packet-detail renderer — same shapes in, compact readable strings out. */
export function formatRegisterValue(snap: RegisterSnapshot | undefined): string {
  if (!snap) return '—'

  const v = snap.value as RegisterValue

  if (v == null) return '—'

  if (typeof v === 'string') return v
  if (typeof v === 'number') return fmtNumber(v)

  if (Array.isArray(v)) {
    return v.map((x) => (typeof x === 'number' ? fmtNumber(x) : String(x))).join(', ')
  }

  // Object shapes — dispatch by distinctive keys
  const obj = v as unknown as Record<string, unknown>

  // NVG sensor
  if ('sensor_id' in obj && 'values' in obj) {
    const vals = (obj.values as unknown[]) ?? []
    const status = obj.status
    const head = vals.map((x) => (typeof x === 'number' ? fmtNumber(x) : String(x))).join(', ')
    return head ? `status=${status}  ${head}` : `status=${status}`
  }

  // BCD (TIME/DATE)
  if (typeof obj.display === 'string') return obj.display as string

  // ADCS_TMP
  if ('celsius' in obj) {
    if (obj.comm_fault) return 'SENSOR FAULT'
    const c = obj.celsius as number | null
    return c == null ? '—' : `${c.toFixed(2)} °C`
  }

  // FSS_TMP1
  if ('fss0_celsius' in obj && 'fss1_celsius' in obj) {
    const a = obj.fss0_celsius as number
    const b = obj.fss1_celsius as number
    return `FSS0 ${a.toFixed(2)} / FSS1 ${b.toFixed(2)} °C`
  }

  // NVG heartbeat
  if ('label' in obj && 'status' in obj && !('sensor_id' in obj) && !('mode' in obj)) {
    return `${obj.label} (${obj.status})`
  }

  // GNC Planner mode
  if ('mode_name' in obj && 'mode' in obj && !('MODE' in obj)) {
    return `${obj.mode_name} (${obj.mode})`
  }

  // GNC counters
  if ('sunspin' in obj && 'detumble' in obj) {
    return `reboot=${obj.reboot}  detumble=${obj.detumble}  sunspin=${obj.sunspin}`
  }

  // Bitfield (STAT/ACT_ERR/SEN_ERR/CONF)
  if ('MODE' in obj || Object.values(obj).some((x) => typeof x === 'boolean')) {
    const parts: string[] = []
    if ('MODE_name' in obj) parts.push(`mode=${obj.MODE_name}`)
    if ('TARGET_ELEV' in obj) parts.push(`elev=${obj.TARGET_ELEV}°`)
    const truthy = Object.entries(obj)
      .filter(([_, val]) => val === true)
      .map(([k]) => k)
    if (truthy.length) parts.push(truthy.join(','))
    else if (!parts.length) parts.push('nominal')
    return parts.join('  ')
  }

  // Generic dict fallback
  return Object.entries(obj)
    .filter(([k]) => !k.startsWith('_') && !k.startsWith('byte'))
    .map(([k, val]) => `${k}=${val}`)
    .join('  ')
}

function fmtNumber(n: number): string {
  if (Number.isInteger(n)) return String(n)
  // compact formatting that preserves precision for small values
  const abs = Math.abs(n)
  if (abs === 0) return '0'
  if (abs >= 1e6 || abs < 1e-4) return n.toExponential(4)
  return n.toFixed(Math.max(2, 6 - Math.ceil(Math.log10(abs + 1e-12))))
}
