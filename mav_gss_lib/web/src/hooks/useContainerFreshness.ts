import { useContext, useEffect, useState } from 'react'
import { ParametersContext } from '@/state/parametersContexts'

export function useContainerFreshness(containerId: string): {
  lastMs: number | null
  ageMs: number | null
  expectedPeriodMs: number | null
} {
  const ctx = useContext(ParametersContext)
  if (!ctx) throw new Error('useContainerFreshness outside ParametersProvider')
  const f = ctx.freshness[containerId]

  // Tick every second so age updates even when no new freshness messages arrive
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  if (!f) return { lastMs: null, ageMs: null, expectedPeriodMs: null }
  return {
    lastMs: f.last_ms,
    ageMs: f.last_ms != null ? Date.now() - f.last_ms : null,
    expectedPeriodMs: f.expected_period_ms,
  }
}
