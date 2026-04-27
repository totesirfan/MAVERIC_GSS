import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Settings, HelpCircle, FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from '@/components/ui/dropdown-menu'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { TabStrip } from '@/components/layout/TabStrip'
import { useRxStatus } from '@/state/rx'
import { colors } from '@/lib/colors'
import type { NavigationTabDef } from '@/components/layout/navigation'
import type { SessionState } from '@/hooks/useSession'

interface GlobalHeaderProps {
  missionName: string
  version: string
  tabs: NavigationTabDef[]
  activeTabId: string
  onTabClick: (id: string) => void
  onLogsClick: () => void
  onConfigClick: () => void
  onHelpClick: () => void
  session?: SessionState
}

function formatElapsed(startedAt: string): string {
  if (!startedAt) return ''
  const start = new Date(startedAt).getTime()
  if (isNaN(start)) return ''
  const diffMs = Date.now() - start
  if (diffMs < 0) return 'just now'
  const s = Math.floor(diffMs / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ${m % 60}m`
  const d = Math.floor(h / 24)
  return `${d}d ${h % 24}h`
}

function extractTimeLocal(startedAt: string): string {
  if (!startedAt) return ''
  const d = new Date(startedAt)
  if (isNaN(d.getTime())) return ''
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
}

/** Per-digit vertical-slide clock animation */
function FlipDigits({ value }: { value: string }) {
  return (
    <>
      {value.split('').map((char, i) => (
        <AnimatePresence mode="popLayout" key={i} initial={false}>
          <motion.span
            key={char}
            style={{ display: 'inline-block' }}
            initial={{ y: 4, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -4, opacity: 0 }}
            transition={{ duration: 0.12, ease: [0.4, 0, 0.2, 1] as const }}
          >
            {char}
          </motion.span>
        </AnimatePresence>
      ))}
    </>
  )
}

/** Returns RX state color for ambient border + status pill */
function useRxStateColor(): { label: string; color: string; borderColor: string } {
  const { status } = useRxStatus()
  const rate = status.pkt_rate
  const silence = status.silence_s
  if (rate > 0) return { label: `${rate.toFixed(1)}/s`, color: colors.success, borderColor: `${colors.success}4D` }
  if (silence >= 180) return { label: `SILENT ${Math.round(silence)}s`, color: colors.warning, borderColor: `${colors.warning}4D` }
  return { label: 'STANDBY', color: colors.dim, borderColor: colors.borderSubtle }
}

export function GlobalHeader({
  missionName,
  version,
  tabs, activeTabId, onTabClick,
  onLogsClick, onConfigClick, onHelpClick,
  session,
}: GlobalHeaderProps) {
  const [now, setNow] = useState(new Date())
  const [elapsed, setElapsed] = useState(() => formatElapsed(session?.startedAt ?? ''))
  const rxState = useRxStateColor()

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (!session?.startedAt) return
    setElapsed(formatElapsed(session.startedAt))
    const id = setInterval(() => setElapsed(formatElapsed(session.startedAt)), 30_000)
    return () => clearInterval(id)
  }, [session?.startedAt])

  const utcTime = now.toISOString().slice(11, 19)
  const utcDate = now.toISOString().slice(0, 10)
  const localDate = now.toLocaleDateString('en-CA')
  const localTime = now.toLocaleTimeString('en-GB', { hour12: false })
  const tz = now.toLocaleTimeString('en-US', { timeZoneName: 'short' }).split(' ').pop() ?? 'local'

  const isUntitled = !session?.sessionTag || session.sessionTag === 'untitled'
  const sessionLabel = isUntitled
    ? `untitled @ ${extractTimeLocal(session?.startedAt ?? '')}`
    : session?.sessionTag ?? ''

  return (
    <header className="shrink-0" style={{ backgroundColor: colors.bgApp }}>
      {/* Row 1: Brand bar — with noise texture + ambient state border */}
      <div className="relative flex items-center h-[34px] px-4" style={{ borderBottom: `1px solid ${rxState.borderColor}`, transition: 'border-color 1s ease' }}>
        {/* Noise texture overlay */}
        <svg className="absolute" style={{ width: 0, height: 0 }} aria-hidden>
          <filter id="header-noise">
            <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="4" stitchTiles="stitch" />
          </filter>
        </svg>
        <div className="absolute inset-0 pointer-events-none" style={{ filter: 'url(#header-noise)', opacity: 0.015, mixBlendMode: 'overlay' }} />

        {/* Brand */}
        <div className="usc-brand flex items-center gap-2 mr-4 cursor-default relative">
          <img src="/usc-shield.png" alt="" className="h-[20px] w-auto" />
          <img src="/maveric-patch.webp" alt="" className="usc-icon size-[24px]" />
          <div className="flex items-center">
            <span className="usc-maveric font-bold text-[13px] tracking-wide transition-colors" style={{ color: colors.value }}>{missionName}</span>
            <span className="usc-gss font-bold text-[13px] tracking-wide transition-colors" style={{ color: colors.value }}>&nbsp;GSS</span>
          </div>
          <span className="text-[11px]" style={{ color: colors.dim }}>v{version}</span>
        </div>

        {/* Session info */}
        {session && (
          <div className="flex items-center gap-2 relative" style={{ minWidth: 0, overflow: 'hidden' }}>
            <span style={{ color: colors.borderStrong, fontSize: '11px', userSelect: 'none' }}>|</span>
            <span
              className="font-mono"
              style={{
                fontSize: '11px',
                color: isUntitled ? colors.textMuted : colors.textSecondary,
                fontStyle: isUntitled ? 'italic' : 'normal',
                minWidth: 0,
                maxWidth: 'clamp(8ch, 24vw, 40ch)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {sessionLabel}
            </span>
            {elapsed && (
              <span style={{ fontSize: '11px', color: colors.textMuted }}>{elapsed}</span>
            )}
            {session?.operator && session?.station && (
              <span style={{
                marginLeft: 8,
                flexShrink: 0,
                whiteSpace: 'nowrap',
                color: colors.textMuted,
                fontFamily: "'Inter', sans-serif",
                fontSize: '11px',
                letterSpacing: '0.04em',
              }}>
                <span style={{ opacity: 0.6 }}>·</span>{' '}
                <span style={{ textTransform: 'uppercase', opacity: 0.7 }}>OP</span>{' '}
                <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                  {session.operator}@{session.station}
                </span>
              </span>
            )}
            <Popover open={session.openNewSession} onOpenChange={session.setOpenNewSession}>
              <PopoverTrigger
                className="px-1.5 py-0.5 rounded text-[11px] cursor-pointer hover:bg-white/[0.04]"
                style={{ color: colors.textMuted }}
              >
                + new
              </PopoverTrigger>
              <PopoverContent
                align="start"
                className="w-64"
                style={{ backgroundColor: colors.bgPanelRaised, borderColor: colors.borderStrong }}
              >
                <NewSessionForm session={session} />
              </PopoverContent>
            </Popover>
            <DropdownMenu>
              <DropdownMenuTrigger
                className="px-1 py-0.5 rounded text-[11px] cursor-pointer hover:bg-white/[0.04]"
                style={{ color: colors.textMuted }}
              >
                &#9660;
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem onClick={() => session.setOpenRename(true)}>
                  Rename Session
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}


        {/* Clock with flip digits — pushed right */}
        <div className="flex items-center gap-3 ml-auto tabular-nums text-[11px] relative">
          <span style={{ color: colors.value }}>{localDate} <FlipDigits value={localTime} /> {tz}</span>
          <span className="font-light" style={{ color: colors.dim }}>{utcDate} <FlipDigits value={utcTime} /> UTC</span>
        </div>
      </div>

      {/* Row 2: Mission bar — frosted glass */}
      <div
        className="flex items-center h-[30px] px-4 backdrop-blur-sm"
        style={{ backgroundColor: colors.modalBackdropHeavy }}
      >
        {/* Tab strip */}
        <TabStrip tabs={tabs} activeId={activeTabId} onTabClick={onTabClick} />

        {/* Utility buttons — pushed right */}
        <div className="flex items-center gap-0.5 ml-auto">
          <Button variant="ghost" size="sm" onClick={onLogsClick} className="h-7 px-2 gap-1.5 text-[11px]" style={{ color: colors.dim }}>
            <FileText className="size-3.5" />
            Logs
          </Button>
          <Button variant="ghost" size="sm" onClick={onConfigClick} className="h-7 px-2 gap-1.5 text-[11px]" style={{ color: colors.dim }}>
            <Settings className="size-3.5" />
            Config
          </Button>
          <Button variant="ghost" size="sm" onClick={onHelpClick} className="h-7 px-2 gap-1.5 text-[11px]" style={{ color: colors.dim }}>
            <HelpCircle className="size-3.5" />
            Help
          </Button>
        </div>
      </div>
    </header>
  )
}

/* ── New Session Form (inside popover) ──────────────────────────── */

function NewSessionForm({ session }: { session: SessionState }) {
  const [newTag, setNewTag] = useState('')
  const [showConfirm, setShowConfirm] = useState(false)
  const [confirmInput, setConfirmInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Auto-focus on mount (component remounts when popover opens)
  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [])

  const canConfirm = session.isTrafficActive ? confirmInput === 'NEW' : true

  const handleSubmit = useCallback(() => {
    setShowConfirm(true)
    setConfirmInput('')
    setError(null)
  }, [])

  const handleConfirm = useCallback(async () => {
    const err = await session.startNewSession(newTag.trim())
    if (err) { setError(err); return }
    setShowConfirm(false)
    session.setOpenNewSession(false)
  }, [newTag, session])

  return (
    <>
      <form onSubmit={(e) => { e.preventDefault(); handleSubmit() }} className="flex flex-col gap-2">
        <Input
          ref={inputRef}
          placeholder="session tag (optional)"
          value={newTag}
          onChange={(e) => setNewTag(e.target.value)}
          className="h-7 text-xs"
          style={{
            backgroundColor: colors.bgApp,
            color: colors.textPrimary,
            borderColor: colors.borderSubtle,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        />
        <button type="submit" className="self-end px-3 py-1 rounded text-[11px] font-medium hover:bg-white/[0.04]" style={{ color: colors.textMuted }}>
          Start
        </button>
      </form>

      <Dialog open={showConfirm} onOpenChange={setShowConfirm}>
        <DialogContent showCloseButton={false} style={{ backgroundColor: colors.bgPanelRaised, borderColor: colors.borderStrong }}>
          <DialogHeader>
            <DialogTitle style={{ color: colors.warning }}>Start New Session?</DialogTitle>
            <DialogDescription style={{ color: colors.textSecondary, fontSize: '12px' }}>
              This will rotate logs and clear the packet list. TX queue and images are preserved.
            </DialogDescription>
          </DialogHeader>
          {session.isTrafficActive && (
            <div className="flex flex-col gap-2 rounded px-3 py-2" style={{ backgroundColor: colors.dangerFill, border: `1px solid ${colors.danger}4D` }}>
              <span style={{ color: colors.danger, fontSize: '12px', fontWeight: 600 }}>&#9888; RX traffic detected</span>
              <Input
                placeholder='Type "NEW" to confirm'
                value={confirmInput}
                onChange={(e) => setConfirmInput(e.target.value)}
                className="h-7 text-xs"
                style={{ backgroundColor: colors.bgApp, color: colors.textPrimary, borderColor: colors.borderSubtle, fontFamily: "'JetBrains Mono', monospace" }}
              />
            </div>
          )}
          {error && <div className="text-xs px-3 py-2 rounded" style={{ color: colors.danger, backgroundColor: colors.dangerFill }}>{error}</div>}
          <DialogFooter>
            <button onClick={() => setShowConfirm(false)} className="px-3 py-1.5 rounded text-xs" style={{ color: colors.textMuted }}>Cancel</button>
            <button onClick={handleConfirm} disabled={!canConfirm} className="px-3 py-1.5 rounded text-xs font-medium disabled:opacity-30"
              style={{ backgroundColor: colors.warningFill, color: colors.warning, border: `1px solid ${colors.warning}4D` }}>
              Confirm
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

/* ── Rename Dialog (rendered by GlobalHeader when session provided) ── */

export function RenameSessionDialog({ session }: { session: SessionState }) {
  return (
    <Dialog open={session.openRename} onOpenChange={(v) => session.setOpenRename(v)}>
      <DialogContent showCloseButton={false} style={{ backgroundColor: colors.bgPanelRaised, borderColor: colors.borderStrong }}>
        {session.openRename && <RenameForm session={session} />}
      </DialogContent>
    </Dialog>
  )
}

function RenameForm({ session }: { session: SessionState }) {
  const [renameTag, setRenameTag] = useState(session.sessionTag)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 50)
  }, [])

  const handleSubmit = useCallback(async () => {
    const err = await session.renameSession(renameTag.trim())
    if (err) { setError(err); return }
    session.setOpenRename(false)
  }, [renameTag, session])

  return (
    <>
      <DialogHeader>
        <DialogTitle style={{ color: colors.textPrimary, fontSize: '14px' }}>Rename Session</DialogTitle>
      </DialogHeader>
      <form onSubmit={(e) => { e.preventDefault(); handleSubmit() }} className="flex flex-col gap-2">
        {error && <div className="text-xs px-2 py-1 rounded" style={{ color: colors.danger, backgroundColor: colors.dangerFill }}>{error}</div>}
        <Input
          ref={inputRef}
          placeholder="session tag"
          value={renameTag}
          onChange={(e) => setRenameTag(e.target.value)}
          className="h-7 text-xs"
          style={{ backgroundColor: colors.bgApp, color: colors.textPrimary, borderColor: colors.borderSubtle, fontFamily: "'JetBrains Mono', monospace" }}
        />
        <DialogFooter>
          <button type="button" onClick={() => session.setOpenRename(false)} className="px-3 py-1.5 rounded text-xs" style={{ color: colors.textMuted }}>Cancel</button>
          <button type="submit" className="px-3 py-1 rounded text-[11px] font-medium hover:bg-white/[0.04]" style={{ color: colors.textMuted }}>Save</button>
        </DialogFooter>
      </form>
    </>
  )
}
