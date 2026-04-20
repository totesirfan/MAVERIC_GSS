import { Check, X, Minus, Loader2 } from 'lucide-react'
import { colors } from '@/lib/colors'
import type {
  UpdatePhase,
  UpdateProgress,
  UpdateUIState,
  UpdatesCheckMeta,
} from '@/lib/types'
import { PHASE_LABELS, PHASE_ORDER, SLATE_ACCENT } from './PreflightScreen.constants'

// =============================================================================
//  UpdatesGroupExtras — inline variant (rendered under the Updates group row)
// =============================================================================

interface UpdatesExtrasProps {
  meta: UpdatesCheckMeta | null
  updateState: UpdateUIState
  updatePhases: Record<UpdatePhase, UpdateProgress>
  /** Unused by the inline variant (idle row handles its own button); kept optional for prop-symmetry with UpdaterStage. */
  onShowConfirm?: () => void
  onCancelConfirm: () => void
  onApplyUpdate: () => void
  onReloadPage: () => void
}

export function UpdatesGroupExtras({
  meta,
  updateState,
  updatePhases,
  onCancelConfirm,
  onApplyUpdate,
  onReloadPage,
}: UpdatesExtrasProps) {
  // idle — inline button is handled in the main row now, so nothing to render here.
  if (updateState === 'idle') return null

  // confirming — header, commit list, planned phases, CONFIRM/CANCEL
  if (updateState === 'confirming' && meta) {
    const header = `Apply ${meta.behind_count} commit${meta.behind_count === 1 ? '' : 's'}?`

    return (
      <div className="mt-3 space-y-2">
        <div
          style={{
            fontSize: 'clamp(11px, 1.2vmin, 13px)',
            color: colors.textPrimary,
            fontFamily: 'Inter, sans-serif',
          }}
        >
          {header}
        </div>
        {meta.behind_count > 0 && meta.commits.length > 0 && (
          <div
            className="max-h-32 overflow-auto space-y-0.5 pr-2"
            style={{
              fontSize: 'clamp(9.5px, 1vmin, 10.5px)',
              color: colors.textSecondary,
              fontFamily: '"JetBrains Mono", monospace',
            }}
          >
            {meta.commits.map((c) => (
              <div key={c.sha}>
                <span style={{ color: colors.textMuted }}>{c.sha}</span>
                {'  '}
                {c.subject}
              </div>
            ))}
          </div>
        )}
        <div
          className="space-y-0.5"
          style={{
            fontSize: 'clamp(9.5px, 1vmin, 10.5px)',
            color: colors.textSecondary,
            fontFamily: '"JetBrains Mono", monospace',
          }}
        >
          <div style={{ color: colors.textMuted }}>This will:</div>
          <div>• git pull --ff-only origin {meta.branch}</div>
          <div>• countdown and restart MAV_WEB.py</div>
        </div>
        <div className="flex gap-2 pt-1">
          <button
            onClick={onApplyUpdate}
            className="rounded tracking-widest"
            style={{
              padding: '0.4rem 1.1rem',
              fontSize: 'clamp(9px, 1vmin, 11px)',
              color: colors.bgApp,
              background: colors.success,
              fontFamily: '"JetBrains Mono", monospace',
              fontWeight: 700,
              border: 'none',
              cursor: 'pointer',
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
            }}
          >
            Confirm
          </button>
          <button
            onClick={onCancelConfirm}
            className="rounded tracking-widest"
            style={{
              padding: '0.4rem 1.1rem',
              fontSize: 'clamp(9px, 1vmin, 11px)',
              color: colors.textSecondary,
              border: `1px solid ${colors.borderStrong}`,
              background: 'transparent',
              fontFamily: '"JetBrains Mono", monospace',
              cursor: 'pointer',
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
            }}
          >
            Cancel
          </button>
        </div>
      </div>
    )
  }

  // applying / failed / reloading — phase list
  if (updateState === 'applying' || updateState === 'failed' || updateState === 'reloading') {
    return (
      <div className="mt-3 space-y-2">
        <PhaseList updatePhases={updatePhases} />
        {updateState === 'reloading' && (
          <div
            className="flex items-center"
            style={{
              gap: '0.5rem',
              fontSize: 'clamp(10px, 1.1vmin, 11.5px)',
              color: colors.textSecondary,
              fontFamily: '"JetBrains Mono", monospace',
            }}
          >
            <Loader2 size={12} className="animate-spin" style={{ color: SLATE_ACCENT }} />
            Restarting…
          </div>
        )}
        {updateState === 'failed' && (
          <button
            onClick={onReloadPage}
            className="rounded tracking-widest"
            style={{
              padding: '0.4rem 1.1rem',
              fontSize: 'clamp(9px, 1vmin, 11px)',
              color: colors.warning,
              border: `1px solid ${colors.warning}66`,
              background: 'transparent',
              fontFamily: '"JetBrains Mono", monospace',
              cursor: 'pointer',
              letterSpacing: '0.22em',
              textTransform: 'uppercase',
            }}
          >
            Reload
          </button>
        )}
      </div>
    )
  }

  return null
}

// =============================================================================
//  PhaseList — shared across both updater variants
// =============================================================================

export function PhaseList({ updatePhases }: { updatePhases: Record<UpdatePhase, UpdateProgress> }) {
  const hasAnyActive = PHASE_ORDER.some((p) => updatePhases[p].status !== 'pending')
  return (
    <div role="status" className="space-y-0.5">
      {PHASE_ORDER.map((phase) => {
        const st = updatePhases[phase]
        if (!hasAnyActive && st.status === 'pending') return null
        const label = PHASE_LABELS[phase]
        let Icon: typeof Loader2 = Minus
        let color: string = colors.neutral
        let spin = false
        if (st.status === 'running') {
          Icon = Loader2
          color = SLATE_ACCENT
          spin = true
        } else if (st.status === 'ok') {
          Icon = Check
          color = colors.success
        } else if (st.status === 'fail') {
          Icon = X
          color = colors.danger
        } else {
          Icon = Minus
          color = colors.textDisabled
        }
        return (
          <div key={phase} className="flex items-start" style={{ gap: '0.5rem', padding: '1px 0' }}>
            <Icon
              size={12}
              className={spin ? 'animate-spin' : undefined}
              style={{ color, marginTop: 2, flexShrink: 0 }}
            />
            <div className="min-w-0 flex-1">
              <span
                style={{
                  fontSize: 'clamp(10px, 1.1vmin, 11px)',
                  color,
                  fontFamily: '"JetBrains Mono", monospace',
                }}
              >
                {label}
              </span>
              {st.detail && (
                <div
                  className="truncate"
                  style={{
                    fontSize: 'clamp(9px, 0.95vmin, 10px)',
                    color: colors.textMuted,
                    fontFamily: '"JetBrains Mono", monospace',
                  }}
                >
                  {st.detail}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// =============================================================================
//  UpdaterStage — card variant (right-column stage-swap)
// =============================================================================

interface UpdaterStageProps {
  meta: UpdatesCheckMeta | null
  updateState: UpdateUIState
  updatePhases: Record<UpdatePhase, UpdateProgress>
  onShowConfirm: () => void
  onCancelConfirm: () => void
  onApplyUpdate: () => void
  onReloadPage: () => void
}

export function UpdaterStage({
  meta,
  updateState,
  updatePhases,
  onShowConfirm,
  onCancelConfirm,
  onApplyUpdate,
  onReloadPage,
}: UpdaterStageProps) {
  const behind = meta?.behind_count ?? 0
  const commits = meta?.commits ?? []

  // Countdown seconds for the "applying" phase (5..1), derived from the
  // latest countdown-phase event. Falls back to 0 when not counting.
  const countdownSec = (() => {
    const cd = updatePhases.countdown
    if (!cd || cd.status !== 'running' || !cd.detail) return 0
    const n = parseInt(cd.detail, 10)
    return Number.isFinite(n) ? n : 0
  })()

  // Status-pill copy + tone mirror the prototype: the pill morphs as the
  // flow advances so a single glance from the panel header tells you where
  // you are (idle/confirming/applying/success/failed).
  const pill = (() => {
    if (updateState === 'confirming') return { text: 'CONFIRM APPLY', tone: 'running' as const }
    if (updateState === 'applying')   return { text: 'APPLYING UPDATE', tone: 'running' as const }
    if (updateState === 'reloading')  return { text: 'UPDATE COMPLETE', tone: 'success' as const }
    if (updateState === 'failed')     return { text: 'UPDATE FAILED', tone: 'fail' as const }
    return {
      text: behind > 0 ? `${behind} COMMIT${behind === 1 ? '' : 'S'} BEHIND` : 'UPDATE AVAILABLE',
      tone: 'warn' as const,
    }
  })()
  const pillColor =
    pill.tone === 'success' ? colors.success :
    pill.tone === 'fail'    ? colors.danger :
    pill.tone === 'running' ? SLATE_ACCENT :
    colors.warning

  return (
    <div
      className="flex flex-col items-stretch"
      style={{
        width: 'clamp(420px, 48vmin, 680px)',
        background: 'rgba(10, 10, 14, 0.82)',
        border: `1px solid rgba(255,255,255,0.09)`,
        borderRadius: 14,
        padding: 'clamp(1.1rem, 2.2vmin, 1.6rem) clamp(1.2rem, 2.4vmin, 1.75rem)',
        backdropFilter: 'blur(28px) saturate(120%)',
        WebkitBackdropFilter: 'blur(28px) saturate(120%)',
        boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.05), 0 40px 80px -40px rgba(0,0,0,0.9)',
        gap: 'clamp(0.6rem, 1.4vmin, 1rem)',
      }}
    >
      {/* Panel header — "UPDATES" label + state-aware status pill */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingBottom: 'clamp(0.7rem, 1.4vmin, 1rem)',
          borderBottom: `1px solid rgba(255,255,255,0.055)`,
        }}
      >
        <div
          style={{
            fontFamily: '"JetBrains Mono", monospace',
            fontSize: 'clamp(9px, 1vmin, 10.5px)',
            letterSpacing: '0.28em',
            color: 'rgba(245,245,245,0.55)',
            textTransform: 'uppercase',
          }}
        >
          Updates · {meta?.branch ?? 'main'}
        </div>
        <div
          style={{
            fontFamily: '"JetBrains Mono", monospace',
            fontSize: 'clamp(8.5px, 0.9vmin, 9.5px)',
            letterSpacing: '0.2em',
            padding: '3px 9px',
            borderRadius: 999,
            color: pillColor,
            border: `1px solid ${pillColor}59`,
            background: `${pillColor}10`,
            textTransform: 'uppercase',
            whiteSpace: 'nowrap',
          }}
        >
          {pill.text}
        </div>
      </div>

      {/* Commit list — no height cap; card grows to fit commits so long
          conventional-commit subjects wrap cleanly instead of being
          truncated or hidden behind a tiny scroll viewport. */}
      {commits.length > 0 && (
        <div
          style={{
            fontFamily: '"JetBrains Mono", monospace',
            fontSize: 'clamp(9.5px, 1vmin, 10.5px)',
            color: 'rgba(245,245,245,0.78)',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.28rem',
            paddingBottom: 'clamp(0.4rem, 1vmin, 0.6rem)',
            borderBottom: `1px solid rgba(255,255,255,0.055)`,
          }}
        >
          {commits.map((c) => (
            <div key={c.sha} style={{ display: 'flex', gap: '0.7rem', alignItems: 'flex-start' }}>
              <span style={{ color: 'rgba(245,245,245,0.42)', flexShrink: 0 }}>{c.sha.slice(0, 7)}</span>
              <span style={{ minWidth: 0, flex: 1, overflowWrap: 'anywhere', lineHeight: 1.5 }}>
                {c.subject}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* State-specific body */}
      {updateState === 'idle' && (
        <button
          onClick={onShowConfirm}
          disabled={!!meta?.button_disabled}
          className="rounded tracking-widest"
          style={{
            padding: '0.55rem 0',
            fontSize: 'clamp(10px, 1.1vmin, 12px)',
            fontFamily: 'Inter, sans-serif',
            fontWeight: 600,
            letterSpacing: '0.15em',
            color: meta?.button_disabled ? colors.textMuted : colors.bgApp,
            background: meta?.button_disabled ? 'transparent' : colors.warning,
            border: meta?.button_disabled ? `1px solid ${colors.borderSubtle}` : 'none',
            cursor: meta?.button_disabled ? 'not-allowed' : 'pointer',
          }}
        >
          APPLY UPDATE
        </button>
      )}
      {updateState === 'idle' && meta?.button_disabled && meta.button_reason && (
        <div
          style={{
            fontSize: 'clamp(9px, 0.95vmin, 10px)',
            color: colors.textMuted,
            textAlign: 'center',
          }}
        >
          {meta.button_reason}
        </div>
      )}

      {updateState === 'confirming' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
          <div
            style={{
              fontSize: 'clamp(9.5px, 1vmin, 10.5px)',
              color: colors.textMuted,
              fontFamily: '"JetBrains Mono", monospace',
            }}
          >
            This will: git pull --ff-only origin {meta?.branch ?? 'main'}, countdown, restart.
          </div>
          <div style={{ display: 'flex', gap: '0.4rem' }}>
            <button
              onClick={onApplyUpdate}
              className="rounded tracking-widest"
              style={{
                flex: 1,
                padding: '0.5rem 0',
                fontSize: 'clamp(10px, 1.1vmin, 12px)',
                fontFamily: 'Inter, sans-serif',
                fontWeight: 600,
                letterSpacing: '0.15em',
                color: colors.bgApp,
                background: colors.success,
                border: 'none',
                cursor: 'pointer',
              }}
            >
              CONFIRM
            </button>
            <button
              onClick={onCancelConfirm}
              className="rounded tracking-widest"
              style={{
                flex: 1,
                padding: '0.5rem 0',
                fontSize: 'clamp(10px, 1.1vmin, 12px)',
                fontFamily: 'Inter, sans-serif',
                fontWeight: 600,
                letterSpacing: '0.15em',
                color: colors.textSecondary,
                background: 'transparent',
                border: `1px solid ${colors.borderSubtle}`,
                cursor: 'pointer',
              }}
            >
              CANCEL
            </button>
          </div>
        </div>
      )}

      {updateState === 'applying' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {PHASE_ORDER.map((phase) => {
            const st = updatePhases[phase] ?? { phase, status: 'pending' as const }
            const label = PHASE_LABELS[phase]
            const Icon =
              st.status === 'ok' ? Check :
              st.status === 'fail' ? X :
              st.status === 'running' ? Loader2 :
              Minus
            const color =
              st.status === 'ok' ? colors.success :
              st.status === 'fail' ? colors.danger :
              st.status === 'running' ? colors.active :
              colors.textMuted
            const isCountdown = phase === 'countdown' && st.status === 'running'
            return (
              <div key={phase} style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                <Icon
                  size={14}
                  color={color}
                  className={st.status === 'running' && !isCountdown ? 'animate-spin' : ''}
                />
                <span
                  style={{
                    fontFamily: 'Inter, sans-serif',
                    fontSize: 'clamp(10px, 1.05vmin, 11.5px)',
                    color: colors.textPrimary,
                    flex: 1,
                  }}
                >
                  {label}
                </span>
                {isCountdown ? (
                  <span
                    aria-live="polite"
                    style={{
                      fontFamily: '"JetBrains Mono", monospace',
                      fontSize: 'clamp(13px, 1.6vmin, 18px)',
                      color: colors.warning,
                      fontWeight: 600,
                      minWidth: '1.5em',
                      textAlign: 'right',
                    }}
                  >
                    {countdownSec}s
                  </span>
                ) : (
                  st.detail && (
                    <span
                      style={{
                        fontFamily: '"JetBrains Mono", monospace',
                        fontSize: 'clamp(9px, 0.95vmin, 10px)',
                        color: colors.textMuted,
                        maxWidth: '55%',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {st.detail}
                    </span>
                  )
                )}
              </div>
            )
          })}
        </div>
      )}

      {updateState === 'reloading' && (
        <div
          style={{
            textAlign: 'center',
            fontFamily: 'Inter, sans-serif',
            fontSize: 'clamp(10px, 1.1vmin, 12px)',
            color: colors.textSecondary,
            padding: '0.5rem 0',
          }}
        >
          Server restarting. Reload in a moment...
          <div style={{ marginTop: '0.5rem' }}>
            <button
              onClick={onReloadPage}
              className="rounded tracking-widest"
              style={{
                padding: '0.45rem 1.2rem',
                fontSize: 'clamp(10px, 1vmin, 11px)',
                fontFamily: 'Inter, sans-serif',
                fontWeight: 600,
                letterSpacing: '0.15em',
                color: colors.bgApp,
                background: SLATE_ACCENT,
                border: 'none',
                cursor: 'pointer',
              }}
            >
              RELOAD
            </button>
          </div>
        </div>
      )}

      {updateState === 'failed' && (
        <div
          style={{
            fontFamily: 'Inter, sans-serif',
            fontSize: 'clamp(10px, 1.05vmin, 11.5px)',
            color: colors.danger,
            padding: '0.5rem 0',
          }}
        >
          Update failed — see phase details above. Try again or pull manually.
          <div style={{ marginTop: '0.5rem' }}>
            <button
              onClick={onCancelConfirm}
              className="rounded tracking-widest"
              style={{
                padding: '0.45rem 1.2rem',
                fontSize: 'clamp(10px, 1vmin, 11px)',
                fontFamily: 'Inter, sans-serif',
                fontWeight: 600,
                letterSpacing: '0.15em',
                color: colors.textSecondary,
                background: 'transparent',
                border: `1px solid ${colors.borderSubtle}`,
                cursor: 'pointer',
              }}
            >
              DISMISS
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
