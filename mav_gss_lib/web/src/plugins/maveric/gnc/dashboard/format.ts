/** Formatting helpers for GNC dashboard values. */

export function fmtVec3(v: number[] | null | undefined, decimals = 4): string {
  if (!v || v.length < 3) return '—'
  return `${v[0].toFixed(decimals)}, ${v[1].toFixed(decimals)}, ${v[2].toFixed(decimals)}`
}

const WEEKDAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export function fmtDateDisplay(date: { display: string; weekday: number } | null | undefined): string {
  if (!date) return '—'
  const wd = WEEKDAY_NAMES[date.weekday] ?? ''
  return wd ? `${date.display} (${wd})` : date.display
}

export function fmtTempC(tmp: { celsius: number | null; comm_fault: boolean } | null | undefined): string {
  if (!tmp) return '—'
  if (tmp.comm_fault) return 'SENSOR FAULT'
  if (tmp.celsius === null) return '—'
  return `${tmp.celsius.toFixed(1)} °C`
}
