import { memo } from 'react'
import { classifyFreshness, formatAge, type Freshness } from '../derive'

type CadenceKind = 'beacon' | 'hk'

export interface CadenceChip {
  label: string
  variant?: 'info' | 'hb-ok' | 'hb-dead' | 'hb-unk'
  title?: string
}

interface Props {
  kind: CadenceKind
  /** Newest ingest timestamp across the fields tracked by this section.
   *  null → no data. */
  latestT: number | null
  /** Current wall time — caller passes a shared useNowMs() value so all
   *  Cadence instances tick together. */
  nowMs: number
  /** Small data chips shown before the timer (Beacon only — MODE, HB). */
  chips?: readonly CadenceChip[]
}

function CadenceInner({ kind, latestT, nowMs, chips }: Props) {
  const state: Freshness = classifyFreshness(latestT, nowMs)
  const ageMs = latestT !== null ? nowMs - latestT : null
  const ageText = formatAge(ageMs)

  const tag = kind === 'beacon' ? 'Beacon' : 'Housekeeping'
  const classes = ['cadence', kind]
  // 'empty' — no packet has arrived yet — is distinct from 'expired'.
  // Keep the default kind accent (info for beacon, muted for hk) so a
  // fresh session doesn't render its section headers in alarm-red.
  if (state === 'stale') classes.push('stale')
  else if (state === 'expired') classes.push('expired')

  const pillText = state === 'stale' ? 'STALE' : state === 'expired' ? 'EXPIRED' : null

  return (
    <div className={classes.join(' ')}>
      <span className="tag">{tag}</span>
      <span className="cluster">
        {chips?.map((c) => (
          <span
            key={c.label}
            className={`mode-chip ${c.variant ?? ''}`.trim()}
            title={c.title}
          >
            {c.label}
          </span>
        ))}
        {pillText && <span className="state-word">{pillText}</span>}
        {(chips?.length || pillText) && <span className="sep">|</span>}
        <span className="kv timer">
          <span className="k">last received</span>
          <span className="v">{ageText}</span>
        </span>
      </span>
    </div>
  )
}

export const Cadence = memo(CadenceInner)
