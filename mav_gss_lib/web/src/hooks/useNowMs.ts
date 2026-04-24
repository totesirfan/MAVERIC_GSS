import { useEffect, useState } from 'react'

/**
 * Shared 1 Hz "now" tick. Every consumer on the page returns the same
 * value and all update together, replacing per-component setInterval
 * patterns that cause drift and extra re-renders.
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
