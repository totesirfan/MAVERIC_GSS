import { useEffect, useState } from 'react'

/**
 * Per-mount 1 Hz "now" tick. Each call creates its own setInterval, so
 * two consumers in the same tree will drift by up to a second. The
 * pattern works today because EpsPage is the single consumer and hands
 * `nowMs` down as a prop to every Cadence instance so they tick together.
 * If a second component ever calls this directly, promote the hook to a
 * shared module-level subscription first.
 *
 * Usage:
 *   const nowMs = useNowMs()
 *   const ageMs = nowMs - someTimestampMs
 */
export function useNowMs(): number {
  const [now, setNow] = useState<number>(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])
  return now
}
