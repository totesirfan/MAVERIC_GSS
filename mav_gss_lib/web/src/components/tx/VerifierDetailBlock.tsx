import type { CommandInstance, VerifierSpec, VerifierOutcome } from '@/lib/types'
import { colors } from '@/lib/colors'

interface VerifierDetailBlockProps {
  instance: CommandInstance | null
  now_ms: number
}

function formatOutcome(spec: VerifierSpec, outcome: VerifierOutcome, t0_ms: number, now_ms: number): string {
  if (outcome.state === 'passed' && outcome.matched_at_ms !== null) {
    return `✓ received @ ${((outcome.matched_at_ms - t0_ms) / 1000).toFixed(1)}s`
  }
  if (outcome.state === 'failed' && outcome.matched_at_ms !== null) {
    return `✗ NACK @ ${((outcome.matched_at_ms - t0_ms) / 1000).toFixed(1)}s`
  }
  if (outcome.state === 'window_expired') {
    return '— window expired'
  }
  const remaining = Math.max(t0_ms + spec.check_window.stop_ms - now_ms, 0) / 1000
  return `⏱ window open — ${remaining.toFixed(0)}s remaining`
}

export function VerifierDetailBlock({ instance, now_ms }: VerifierDetailBlockProps) {
  if (!instance) return null
  return (
    <div className="space-y-0.5">
      <div className="text-[11px] font-bold uppercase tracking-wide" style={{ color: colors.dim }}>Verifiers</div>
      {instance.verifier_set.verifiers.map(spec => {
        const o = instance.outcomes[spec.verifier_id] ?? { state: 'pending', matched_at_ms: null, match_event_id: null }
        const dim = spec.stage === 'failed' && o.state !== 'passed'
        return (
          <div key={spec.verifier_id} className="flex items-center gap-2 text-xs">
            <span style={{ color: dim ? colors.sep : colors.label, width: 120 }}>{spec.display_label}{spec.stage === 'failed' ? ' (NACK)' : ''}</span>
            <span style={{ color: colors.value }}>{formatOutcome(spec, o, instance.t0_ms, now_ms)}</span>
          </div>
        )
      })}
    </div>
  )
}
