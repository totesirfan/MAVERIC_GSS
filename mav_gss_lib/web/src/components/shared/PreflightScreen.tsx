import { useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Check, X, AlertTriangle, Minus, Loader2 } from 'lucide-react'
import { colors } from '@/lib/colors'
import type {
  PreflightCheck,
  PreflightSummary,
  UpdatePhase,
  UpdateProgress,
  UpdatesCheckMeta,
  UpdateUIState,
} from '@/lib/types'
import { PlanetGlobe } from './PlanetGlobe'

// =============================================================================
//  Constants
// =============================================================================

const STATUS_ICON = {
  ok: Check,
  fail: X,
  warn: AlertTriangle,
  skip: Minus,
} as const

const STATUS_COLOR = {
  ok: colors.success,
  fail: colors.danger,
  warn: colors.warning,
  skip: colors.neutral,
} as const

const GROUP_LABELS: Record<string, string> = {
  python_deps: 'Python Dependencies',
  gnuradio: 'GNU Radio / PMT',
  config: 'Config Files',
  web_build: 'Web Build',
  zmq: 'ZMQ Addresses',
  updates: 'Updates',
}

const PHASE_LABELS: Record<UpdatePhase, string> = {
  git_pull:       'git pull',
  pip_install:    'pip install',
  bootstrap_venv: 'bootstrap venv',
  restart:        'restart',
}

const PHASE_ORDER: UpdatePhase[] = ['git_pull', 'bootstrap_venv', 'pip_install', 'restart']

// Welcome-screen slate accent (kept local so the rest of the app's cyan
// colors.active stays untouched).
const SLATE_ACCENT = '#C8D0DC'
const USC_GOLD     = '#FFCC00'

// =============================================================================
//  Props
// =============================================================================

interface Props {
  checks: PreflightCheck[]
  summary: PreflightSummary | null
  connected: boolean
  dismissing: boolean
  onContinue: () => void
  onRerun: () => void
  updateState: UpdateUIState
  updatePhases: Record<UpdatePhase, UpdateProgress>
  onShowConfirm: () => void
  onCancelConfirm: () => void
  onApplyUpdate: () => void
  onReloadPage: () => void
  /** Optional — semver string shown in the meta strip. */
  version?: string
  /** Optional — short git SHA shown in the meta strip. */
  buildSha?: string
}

// =============================================================================
//  Main component
// =============================================================================

export function PreflightScreen({
  checks,
  summary,
  connected,
  dismissing,
  onContinue,
  onRerun,
  updateState,
  updatePhases,
  onShowConfirm,
  onCancelConfirm,
  onApplyUpdate,
  onReloadPage,
  version,
  buildSha,
}: Props) {
  const groups = useMemo(() => {
    const map = new Map<string, PreflightCheck[]>()
    for (const c of checks) {
      const arr = map.get(c.group) || []
      arr.push(c)
      map.set(c.group, arr)
    }
    return map
  }, [checks])

  // "All passed" requires no failures AND no warnings AND no skips.
  // summary.ready only tracks failures, so we tighten the check for the
  // visible label/button tone — e.g., an offline-skipped update check should
  // not render as "ALL CHECKS PASSED" just because nothing failed.
  const skipped = summary?.skipped ?? 0
  const allPassed =
    summary?.ready === true &&
    summary.warnings === 0 &&
    skipped === 0
  const hasFails = summary ? summary.failed > 0 : false
  const running = !summary && connected && checks.length > 0

  // Only list issues — filter each group to its non-ok checks, and drop
  // groups that have nothing to report. The happy path leaves the whole
  // check grid collapsed and jumps straight to the summary line.
  const nonUpdatesGroups = Array.from(groups.entries())
    .filter(([id]) => id !== 'updates')
    .map(([id, groupChecks]) => {
      const issues = groupChecks.filter((c) => c.status !== 'ok')
      return [id, issues] as const
    })
    .filter(([, issues]) => issues.length > 0)

  const updatesEntry = groups.get('updates')
  const updatesMeta = (updatesEntry?.[0]?.meta as UpdatesCheckMeta | null | undefined) ?? null
  const updatesHasIssue = !!updatesEntry?.some((c) => c.status !== 'ok')
  // Keep the Updates row visible when the user is mid-flow (confirming /
  // applying / failed / reloading) even if the check itself isn't "warn" yet.
  const showUpdatesRow = updatesHasIssue || updateState !== 'idle'
  const showInlineApply =
    updateState === 'idle' &&
    updatesMeta?.button === 'apply' &&
    !updatesMeta.button_disabled

  // Only render the systems-check section if there's anything to report.
  const hasAnyIssues = nonUpdatesGroups.length > 0 || showUpdatesRow

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-hidden"
      style={{ backgroundColor: '#040408' }}
      animate={dismissing ? { opacity: 0 } : { opacity: 1 }}
      transition={{ duration: 0.8, ease: [0.4, 0, 0.2, 1] }}
    >
      {/* Backdrop texture */}
      <GrainOverlay />

      {/* Composition — flex-centered two columns */}
      <div
        className="relative flex items-center justify-center"
        style={{
          gap: 'clamp(2.75rem, 7vw, 7.5rem)',
          padding: 'clamp(1rem, 3vw, 3rem)',
        }}
      >
        {/* ================= LEFT: content column ================= */}
        <div className="flex flex-col min-w-0" style={{ maxWidth: 620 }}>
          {/* Brand row: patch + USC */}
          <div
            className="flex items-center"
            style={{
              gap: 'clamp(1.5rem, 2.6vw, 2.5rem)',
              marginBottom: 'clamp(0.9rem, 2.2vmin, 1.6rem)',
            }}
          >
            <PatchWrap running={running} />
            <UscBlock />
          </div>

          {/* Hero title */}
          <motion.h1
            className="font-extrabold"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.15 }}
            style={{
              fontSize: 'clamp(2.25rem, 4.8vw, 4.25rem)',
              letterSpacing: '-0.028em',
              lineHeight: 0.9,
              background: 'linear-gradient(180deg, #ffffff 0%, rgba(255,255,255,0.55) 100%)',
              WebkitBackgroundClip: 'text',
              backgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              color: 'transparent',
            }}
          >
            MAVERIC
          </motion.h1>

          {/* Subtitle */}
          <motion.div
            className="uppercase"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.28 }}
            style={{
              fontSize: 'clamp(10px, 1.1vmin, 13px)',
              fontWeight: 500,
              letterSpacing: '0.28em',
              color: colors.textMuted,
              marginTop: 'clamp(0.35rem, 0.8vmin, 0.6rem)',
            }}
          >
            Ground Station Software
          </motion.div>

          {/* Meta inline */}
          <MetaInline connected={connected} version={version} buildSha={buildSha} />

          {/* Section divider + groups grid — only visible when there are
              issues (or an update flow is in progress). The happy path
              jumps straight from the meta row to the summary line. */}
          {hasAnyIssues && (
            <>
              <SectionDivider label="Systems Check" />

              <div
                className="grid"
                style={{
                  gridTemplateColumns: '1fr 1fr',
                  columnGap: 'clamp(1.25rem, 3vw, 2.25rem)',
                  rowGap: 'clamp(0.9rem, 2vmin, 1.25rem)',
                }}
              >
                <AnimatePresence mode="popLayout">
                  {nonUpdatesGroups.map(([groupId, groupChecks], idx) => (
                    <GroupCell
                      key={groupId}
                      groupId={groupId}
                      groupChecks={groupChecks}
                      groupIndex={idx}
                    />
                  ))}

                  {showUpdatesRow && updatesEntry && (
                    <div
                      key="updates"
                      className="col-span-2"
                      style={{
                        marginTop: 'clamp(0.25rem, 0.6vmin, 0.45rem)',
                        paddingTop: 'clamp(0.5rem, 1.1vmin, 0.75rem)',
                        borderTop:
                          nonUpdatesGroups.length > 0
                            ? `1px solid ${colors.borderSubtle}`
                            : 'none',
                      }}
                    >
                      <GroupCell
                        groupId="updates"
                        groupChecks={updatesEntry}
                        groupIndex={nonUpdatesGroups.length}
                        inlineAction={
                          showInlineApply ? (
                            <InlineApplyButton
                              behindCount={updatesMeta?.behind_count ?? 0}
                              onClick={onShowConfirm}
                            />
                          ) : null
                        }
                      />
                      <UpdatesGroupExtras
                        meta={updatesMeta}
                        updateState={updateState}
                        updatePhases={updatePhases}
                        onShowConfirm={onShowConfirm}
                        onCancelConfirm={onCancelConfirm}
                        onApplyUpdate={onApplyUpdate}
                        onReloadPage={onReloadPage}
                      />
                    </div>
                  )}
                </AnimatePresence>
              </div>
            </>
          )}

          {/* Running / connecting captions (visible while checks populate) */}
          {!connected && checks.length === 0 && <ConnectingCaption />}
          {running && <RunningCaption />}

          {/* Summary + launch */}
          {summary && (
            <SummaryLine
              allPassed={allPassed}
              hasFails={hasFails}
              failed={summary.failed}
              warnings={summary.warnings}
              skipped={skipped}
            />
          )}
          {summary && (
            <LaunchArea
              allPassed={allPassed}
              showRerun={!allPassed}
              onContinue={onContinue}
              onRerun={onRerun}
            />
          )}
        </div>

        {/* ================= RIGHT: visual column ================= */}
        <div className="flex items-center justify-center min-w-0">
          <PlanetGlobe />
        </div>
      </div>

      <style>{`
        @keyframes preflight-pulse {
          0%, 100% { opacity: 0.5; transform: translate(-50%, -50%) scale(1); }
          50%      { opacity: 1;   transform: translate(-50%, -50%) scale(1.08); }
        }
      `}</style>
    </motion.div>
  )
}

// =============================================================================
//  Sub-components
// =============================================================================

function GrainOverlay() {
  return (
    <svg
      className="fixed inset-0 pointer-events-none"
      style={{ zIndex: 60, mixBlendMode: 'overlay', width: '100%', height: '100%' }}
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <filter id="preflightGrainFilter">
        <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" stitchTiles="stitch" />
        <feColorMatrix values="0 0 0 0 0.92  0 0 0 0 0.92  0 0 0 0 0.92  0 0 0 0.9 0" />
      </filter>
      <rect width="100%" height="100%" filter="url(#preflightGrainFilter)" />
    </svg>
  )
}

function PatchWrap({ running }: { running: boolean }) {
  return (
    <div
      className="relative flex-shrink-0"
      style={{
        width: 'clamp(104px, 11vmin, 150px)',
        height: 'clamp(104px, 11vmin, 150px)',
      }}
    >
      {/* Ambient pulse glow — only while preflight is running */}
      {running && (
        <motion.div
          className="absolute rounded-full pointer-events-none"
          style={{
            inset: '-30%',
            background:
              'radial-gradient(circle, rgba(200, 210, 220, 0.16) 0%, rgba(200, 210, 220, 0.05) 40%, transparent 65%)',
            filter: 'blur(6px)',
            zIndex: -1,
          }}
          initial={{ scale: 1, opacity: 0.55 }}
          animate={{ scale: [1, 1.09, 1], opacity: [0.55, 1, 0.55] }}
          transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}
      <motion.img
        src="/maveric-patch.webp"
        alt="MAVERIC mission patch"
        className="w-full h-full"
        style={{
          objectFit: 'contain',
          filter: `drop-shadow(0 0 28px rgba(180, 188, 200, 0.22))`,
        }}
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
      />
    </div>
  )
}

function UscBlock() {
  return (
    <motion.div
      className="flex flex-col items-start min-w-0"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.08, ease: 'easeOut' }}
      style={{ gap: 'clamp(0.4rem, 0.9vmin, 0.7rem)' }}
    >
      <img
        src="/usc-primary-logotype-dark.png"
        alt="University of Southern California primary logotype"
        className="block select-none"
        style={{
          width: 'clamp(200px, 20vmin, 290px)',
          height: 'auto',
          opacity: 0.94,
        }}
      />
      <span
        style={{
          fontFamily: '"Cormorant Garamond", "Adobe Caslon Pro", Georgia, serif',
          fontSize: 'clamp(13px, 1.7vmin, 18px)',
          color: 'rgba(245, 245, 245, 0.78)',
          lineHeight: 1.2,
          whiteSpace: 'nowrap',
        }}
      >
        <span style={{ color: USC_GOLD, fontWeight: 600 }}>S</span>pace{' '}
        <span style={{ color: USC_GOLD, fontWeight: 600 }}>E</span>ngineering{' '}
        <span style={{ color: USC_GOLD, fontWeight: 600 }}>R</span>esearch{' '}
        <span style={{ color: USC_GOLD, fontWeight: 600 }}>C</span>enter
      </span>
    </motion.div>
  )
}

function MetaInline({
  connected,
  version,
  buildSha,
}: {
  connected: boolean
  version?: string
  buildSha?: string
}) {
  return (
    <motion.div
      className="flex items-center uppercase"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.45, delay: 0.35 }}
      style={{
        gap: '0.55rem',
        fontFamily: '"JetBrains Mono", monospace',
        fontSize: 'clamp(10px, 1.1vmin, 12.5px)',
        letterSpacing: '0.13em',
        color: 'rgba(245, 245, 245, 0.72)',
        whiteSpace: 'nowrap',
        marginTop: 'clamp(0.6rem, 1.3vmin, 0.95rem)',
      }}
    >
      <span>
        <span
          className="inline-block align-middle"
          style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: connected ? colors.success : colors.neutral,
            boxShadow: connected ? '0 0 12px rgba(60, 201, 142, 0.85)' : 'none',
            marginRight: '0.4rem',
          }}
        />
        {connected ? 'Connected' : 'Offline'}
      </span>
      {version && (
        <>
          <span style={{ color: 'rgba(255,255,255,0.22)', fontSize: '1.1em' }}>·</span>
          <span>v{version}</span>
        </>
      )}
      {buildSha && (
        <>
          <span style={{ color: 'rgba(255,255,255,0.22)', fontSize: '1.1em' }}>·</span>
          <span>Build {buildSha}</span>
        </>
      )}
    </motion.div>
  )
}

function SectionDivider({ label }: { label: string }) {
  const lineStyle: React.CSSProperties = {
    flex: 1,
    height: 1,
    background:
      'linear-gradient(90deg, rgba(200,210,220,0.02) 0%, rgba(200,210,220,0.28) 40%, rgba(200,210,220,0.28) 60%, rgba(200,210,220,0.02) 100%)',
  }
  return (
    <div
      className="flex items-center overflow-hidden"
      style={{
        gap: '0.95rem',
        margin: 'clamp(1.4rem, 3vmin, 2rem) 0 clamp(0.9rem, 2vmin, 1.3rem)',
      }}
    >
      <div style={lineStyle} />
      <div
        className="uppercase flex-shrink-0"
        style={{
          fontFamily: '"JetBrains Mono", monospace',
          fontSize: 'clamp(9px, 1vmin, 11.5px)',
          letterSpacing: '0.3em',
          color: 'rgba(255,255,255,0.48)',
        }}
      >
        {label}
      </div>
      <div style={lineStyle} />
    </div>
  )
}

function GroupCell({
  groupId,
  groupChecks,
  inlineAction,
  groupIndex = 0,
}: {
  groupId: string
  groupChecks: PreflightCheck[]
  inlineAction?: React.ReactNode
  groupIndex?: number
}) {
  const isUpdates = groupId === 'updates'
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: groupIndex * 0.09, ease: [0.2, 0.65, 0.3, 0.95] }}
    >
      <div
        className="uppercase flex items-center justify-between"
        style={{
          fontSize: 'clamp(9.5px, 1vmin, 11px)',
          letterSpacing: '0.2em',
          color: colors.neutral,
          marginBottom: '0.4rem',
          fontFamily: 'Inter, sans-serif',
        }}
      >
        <span>{GROUP_LABELS[groupId] || groupId}</span>
      </div>
      <div className="space-y-0.5">
        {groupChecks.map((check, i) => {
          const Icon = STATUS_ICON[check.status] || Minus
          const color = STATUS_COLOR[check.status] || colors.neutral
          return (
            <motion.div
              key={`${groupId}-${i}`}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{
                duration: 0.3,
                delay: groupIndex * 0.09 + 0.12 + i * 0.05,
                ease: [0.2, 0.65, 0.3, 0.95],
              }}
              className="flex items-start"
              style={{ gap: '0.55rem', padding: '1px 0' }}
            >
              <Icon
                size={12}
                style={{ color, marginTop: 2, flexShrink: 0 }}
              />
              <div className="min-w-0 flex-1">
                <span
                  style={{
                    color: check.status === 'ok' ? colors.textSecondary : color,
                    fontFamily: '"JetBrains Mono", monospace',
                    fontSize: 'clamp(10px, 1.1vmin, 12.5px)',
                    letterSpacing: '0.04em',
                  }}
                >
                  {check.label}
                  {check.detail ? ` — ${check.detail}` : ''}
                </span>
                {check.fix && check.status !== 'ok' && (
                  <div
                    style={{
                      fontSize: 'clamp(9px, 0.95vmin, 10.5px)',
                      color: colors.dim,
                      fontFamily: '"JetBrains Mono", monospace',
                      marginTop: 1,
                    }}
                  >
                    {check.fix}
                  </div>
                )}
              </div>
              {/* Inline action slot (used by the Updates row for Apply Update) */}
              {isUpdates && i === groupChecks.length - 1 && inlineAction}
            </motion.div>
          )
        })}
      </div>
    </motion.div>
  )
}

function InlineApplyButton({
  behindCount,
  onClick,
}: {
  behindCount: number
  onClick: () => void
}) {
  const label =
    behindCount > 0
      ? `Apply · ${behindCount} commit${behindCount === 1 ? '' : 's'}`
      : 'Apply Update'
  return (
    <motion.button
      onClick={onClick}
      className="inline-flex items-center uppercase rounded-full cursor-pointer"
      style={{
        marginLeft: '0.55rem',
        padding: '0.28rem 0.75rem',
        border: `1px solid ${colors.warning}73`,
        background: `${colors.warning}10`,
        color: colors.warning,
        fontFamily: '"JetBrains Mono", monospace',
        fontSize: 'clamp(9px, 0.95vmin, 10px)',
        letterSpacing: '0.22em',
        whiteSpace: 'nowrap',
        flexShrink: 0,
      }}
      animate={{
        boxShadow: [
          `0 0 0 ${colors.warning}00`,
          `0 0 22px ${colors.warning}4D`,
          `0 0 0 ${colors.warning}00`,
        ],
      }}
      transition={{ duration: 3.2, repeat: Infinity, ease: 'easeInOut' }}
      whileHover={{
        background: `${colors.warning}26`,
        borderColor: `${colors.warning}D9`,
        y: -1,
      }}
    >
      {label}
    </motion.button>
  )
}

function RunningCaption() {
  return (
    <div
      className="flex items-center justify-center uppercase"
      style={{
        gap: '0.5rem',
        marginTop: 'clamp(1.1rem, 2.2vmin, 1.6rem)',
        paddingTop: 'clamp(0.7rem, 1.4vmin, 1rem)',
        borderTop: `1px solid ${colors.borderSubtle}`,
        fontFamily: '"JetBrains Mono", monospace',
        fontSize: 'clamp(9px, 1vmin, 11.5px)',
        letterSpacing: '0.3em',
        color: SLATE_ACCENT,
      }}
    >
      <Loader2 size={12} className="animate-spin" style={{ color: SLATE_ACCENT }} />
      Running preflight checks…
    </div>
  )
}

function ConnectingCaption() {
  return (
    <div
      className="flex items-center justify-center py-4"
      style={{ gap: '0.5rem' }}
    >
      <Loader2 size={14} className="animate-spin" style={{ color: colors.neutral }} />
      <span
        style={{
          fontFamily: '"JetBrains Mono", monospace',
          fontSize: 'clamp(10px, 1.1vmin, 12.5px)',
          color: colors.neutral,
        }}
      >
        Connecting…
      </span>
    </div>
  )
}

function SummaryLine({
  allPassed,
  hasFails,
  failed,
  warnings,
  skipped,
}: {
  allPassed: boolean
  hasFails: boolean
  failed: number
  warnings: number
  skipped: number
}) {
  return (
    <motion.div
      className="uppercase"
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.1 }}
      style={{
        marginTop: 'clamp(1.1rem, 2.2vmin, 1.6rem)',
        paddingTop: 'clamp(0.7rem, 1.4vmin, 1rem)',
        borderTop: `1px solid ${colors.borderSubtle}`,
        fontFamily: '"JetBrains Mono", monospace',
        fontSize: 'clamp(9px, 1vmin, 11.5px)',
        letterSpacing: '0.3em',
        color: allPassed ? colors.success : hasFails ? colors.danger : colors.warning,
      }}
    >
      {allPassed
        ? 'ALL CHECKS PASSED'
        : `${failed} FAILED · ${warnings} WARN${skipped > 0 ? ` · ${skipped} SKIP` : ''}`}
    </motion.div>
  )
}

function LaunchArea({
  allPassed,
  showRerun,
  onContinue,
  onRerun,
}: {
  allPassed: boolean
  showRerun: boolean
  onContinue: () => void
  onRerun: () => void
}) {
  return (
    <motion.div
      className="flex flex-col items-start"
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.18 }}
      style={{
        marginTop: 'clamp(1rem, 2vmin, 1.4rem)',
        gap: 'clamp(0.45rem, 1vmin, 0.7rem)',
      }}
    >
      <button
        onClick={onContinue}
        className="rounded cursor-pointer tracking-widest uppercase"
        style={{
          padding: 'clamp(0.65rem, 1.5vmin, 0.85rem) clamp(1.8rem, 4vmin, 2.6rem)',
          minWidth: 'clamp(180px, 22vmin, 240px)',
          fontFamily: '"JetBrains Mono", monospace',
          fontSize: 'clamp(10px, 1.15vmin, 12px)',
          letterSpacing: '0.28em',
          fontWeight: allPassed ? 700 : 500,
          color: allPassed ? colors.bgApp : colors.textPrimary,
          background: allPassed ? colors.success : 'transparent',
          border: allPassed ? 'none' : `1px solid ${colors.borderStrong}`,
          boxShadow: allPassed ? `0 0 28px ${colors.success}40` : 'none',
          transition: 'background 220ms ease, border-color 220ms ease, box-shadow 220ms ease, transform 220ms ease',
        }}
      >
        {allPassed ? 'Launch' : 'Continue Anyway'}
      </button>
      {showRerun && (
        <button
          onClick={onRerun}
          className="rounded cursor-pointer tracking-widest uppercase"
          style={{
            padding: '0.5rem 1.5rem',
            minWidth: 'clamp(180px, 22vmin, 240px)',
            fontFamily: '"JetBrains Mono", monospace',
            fontSize: 'clamp(9px, 1vmin, 10.5px)',
            letterSpacing: '0.28em',
            color: colors.textSecondary,
            border: `1px solid ${colors.borderStrong}`,
            background: 'transparent',
          }}
        >
          Rerun
        </button>
      )}
    </motion.div>
  )
}

// =============================================================================
//  Updates group extras — button, confirm panel, phase list, failed/reloading.
//  (Idle-state APPLY UPDATE button is now rendered inline inside the Updates
//  check row, so this component returns null for the idle case.)
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

function UpdatesGroupExtras({
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
    const header =
      meta.behind_count > 0
        ? `Apply ${meta.behind_count} commit${meta.behind_count === 1 ? '' : 's'}?`
        : 'Install Python dependencies?'

    const pipBullet: string | null = (() => {
      if (meta.missing_pip_deps.length > 0) {
        return `pip install -r requirements.txt (${meta.missing_pip_deps.length} new package${meta.missing_pip_deps.length === 1 ? '' : 's'})`
      }
      if (meta.requirements_changed) {
        return 'pip install -r requirements.txt (refresh)'
      }
      if (meta.requirements_out_of_sync) {
        return 'retry pip install -r requirements.txt (last install incomplete)'
      }
      return null
    })()

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
          {meta.behind_count > 0 && <div>• git pull origin {meta.branch}</div>}
          {pipBullet && <div>• {pipBullet}</div>}
          <div>• restart MAV_WEB.py</div>
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

function PhaseList({ updatePhases }: { updatePhases: Record<UpdatePhase, UpdateProgress> }) {
  const hasAnyActive = PHASE_ORDER.some((p) => updatePhases[p].status !== 'pending')
  return (
    <div className="space-y-0.5">
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
