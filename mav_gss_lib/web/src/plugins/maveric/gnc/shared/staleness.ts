/** Three-tier staleness model.
 *
 *   fresh     : age < MEDIUM_MS          (normal display)
 *   warning   : MEDIUM_MS ≤ age < HIGH_MS (dimmed + warning tone)
 *   critical  : age ≥ HIGH_MS            (heavily dimmed + danger tone)
 *
 *  Thresholds are uniform across registers. Fast vs slow-changing
 *  distinction is operator judgement, not automatic — a value that
 *  the satellite only emits once a day should still show its age.
 */
export const MEDIUM_MS = 30 * 60 * 1000           // 30 minutes
export const HIGH_MS   = 12 * 60 * 60 * 1000      // 12 hours

export type StaleLevel = 'fresh' | 'warning' | 'critical'

/** Shared opacity scale used by FieldDisplay + FlagDot so the dashboard
 *  dims consistently whether a value is rendered as text or a flag dot. */
export const STALE_OPACITY: Record<StaleLevel, number> = {
  fresh:    1.0,
  warning:  0.65,
  critical: 0.4,
}
/** Opacity when we've never seen data for this field at all (e.g.
 *  placeholder panels awaiting a v2 command integration). */
export const NO_DATA_OPACITY = 0.35

export function ageMs(receivedAt: number | null | undefined, nowMs: number): number | null {
  if (receivedAt == null) return null
  return nowMs - receivedAt
}

export function staleLevel(age: number | null): StaleLevel {
  if (age == null) return 'critical'      // no data ever seen
  if (age >= HIGH_MS)   return 'critical'
  if (age >= MEDIUM_MS) return 'warning'
  return 'fresh'
}

export function formatAge(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 1000) return 'now'
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  const d = Math.floor(h / 24)
  return `${d}d`
}
