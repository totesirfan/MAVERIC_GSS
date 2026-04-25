import type { CommandInstance, VerifierSpec, VerifierOutcome } from '@/lib/types'
import { colors } from '@/lib/colors'

interface VerifierTickStripProps {
  instance: CommandInstance | null
  now_ms: number
}

function dotColor(state: string, _tone: string): string {
  if (state === 'passed') return colors.success
  if (state === 'failed') return colors.danger
  if (state === 'window_expired') return colors.dim
  return 'transparent' // pending → outline only
}

function shouldPulse(spec: VerifierSpec, outcome: VerifierOutcome, now_ms: number, t0_ms: number): boolean {
  if (outcome.state !== 'pending') return false
  const elapsed = now_ms - t0_ms
  return elapsed / spec.check_window.stop_ms > 0.8
}

export function VerifierTickStrip({ instance, now_ms }: VerifierTickStripProps) {
  if (!instance) {
    return <span style={{ display: 'inline-block', width: 60 }} aria-hidden />
  }
  // Show one dot per verifier (skip NACK unless fired).
  const active: VerifierSpec[] = instance.verifier_set.verifiers.filter(v => {
    if (v.stage === 'failed') {
      return instance.outcomes[v.verifier_id]?.state === 'passed'
    }
    return true
  })
  const nackFired = instance.verifier_set.verifiers.some(
    v => v.stage === 'failed' && instance.outcomes[v.verifier_id]?.state === 'passed'
  )
  return (
    <span className="inline-flex items-center gap-1" title={instance.stage.toUpperCase()}>
      {active.map(v => {
        const o = instance.outcomes[v.verifier_id] ?? { state: 'pending', matched_at_ms: null, match_event_id: null }
        const filled = o.state === 'passed' || o.state === 'failed' || o.state === 'window_expired'
        const pulse = shouldPulse(v, o, now_ms, instance.t0_ms)
        return (
          <span key={v.verifier_id}
            className={`inline-block rounded-full ${pulse ? 'animate-pulse-warning' : ''}`}
            style={{
              width: 12, height: 12,
              backgroundColor: filled ? dotColor(o.state, v.display_tone) : 'transparent',
              border: filled ? 'none' : `2px solid ${colors.active}`,
              boxShadow: filled ? `0 0 0 1px ${colors.borderStrong}` : undefined,
            }}
            title={`${v.display_label} · ${o.state}`}
          />
        )
      })}
      {nackFired && (
        <span className="ml-0.5 text-[10px] font-bold" style={{ color: colors.danger }}>!</span>
      )}
    </span>
  )
}
