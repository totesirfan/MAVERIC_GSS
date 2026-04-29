import { useContext } from 'react'
import { ParametersContext } from '@/state/parametersContexts'
import { useNowMs } from '@/hooks/useNowMs'

export function useContainerFreshness(containerId: string): {
  lastMs: number | null
  ageMs: number | null
  expectedPeriodMs: number | null
} {
  const ctx = useContext(ParametersContext)
  if (!ctx) throw new Error('useContainerFreshness outside ParametersProvider')
  const f = ctx.freshness[containerId]
  const nowMs = useNowMs()

  if (!f) return { lastMs: null, ageMs: null, expectedPeriodMs: null }
  return {
    lastMs: f.last_ms,
    ageMs: f.last_ms != null ? nowMs - f.last_ms : null,
    expectedPeriodMs: f.expected_period_ms,
  }
}
