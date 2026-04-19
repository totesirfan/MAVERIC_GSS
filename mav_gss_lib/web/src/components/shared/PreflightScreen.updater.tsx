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
  onShowConfirm: () => void
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

  return (
    <div
      className="flex flex-col items-stretch"
      style={{
        width: 'clamp(320px, 34vmin, 460px)',
        padding: 'clamp(1rem, 2vmin, 1.5rem)',
        background: 'rgba(14, 14, 14, 0.85)',
        border: `1px solid ${colors.borderSubtle}`,
        borderRadius: 10,
        boxShadow: '0 0 30px rgba(0, 0, 0, 0.4)',
        gap: 'clamp(0.5rem, 1.2vmin, 0.9rem)',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div
          style={{
            fontFamily: 'Inter, sans-serif',
            fontWeight: 600,
            letterSpacing: '0.12em',
            fontSize: 'clamp(11px, 1.2vmin, 13px)',
            color: SLATE_ACCENT,
            textTransform: 'uppercase',
          }}
        >
          Update Available
        </div>
        <div
          style={{
            fontFamily: '"JetBrains Mono", monospace',
            fontSize: 'clamp(9.5px, 1vmin, 11px)',
            color: colors.textMuted,
          }}
        >
          {meta?.branch ?? 'main'} · {behind} commit{behind === 1 ? '' : 's'} behind
        </div>
      </div>

      {/* Commit list */}
      {commits.length > 0 && (
        <div
          className="overflow-auto"
          style={{
            maxHeight: 'clamp(120px, 22vmin, 200px)',
            fontFamily: '"JetBrains Mono", monospace',
            fontSize: 'clamp(9.5px, 1vmin, 10.5px)',
            color: colors.textSecondary,
            borderTop: `1px solid ${colors.borderSubtle}`,
            borderBottom: `1px solid ${colors.borderSubtle}`,
            padding: '0.5rem 0',
          }}
        >
          {commits.map((c) => (
            <div key={c.sha} style={{ display: 'flex', gap: '0.6rem', padding: '2px 0' }}>
              <span style={{ color: colors.textMuted, flexShrink: 0 }}>{c.sha.slice(0, 7)}</span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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
