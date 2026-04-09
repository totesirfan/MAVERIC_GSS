import { useState, useEffect, useRef, useCallback } from 'react'
import { Satellite, Settings, HelpCircle, FileText, Maximize, Minimize, Camera, ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from '@/components/ui/dropdown-menu'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { colors } from '@/lib/colors'
import type { PluginPageDef } from '@/plugins/registry'
import type { SessionState } from '@/hooks/useSession'

interface GlobalHeaderProps {
  missionName: string
  version: string
  page?: string | null
  plugins?: PluginPageDef[]
  onPluginClick?: (id: string) => void
  onBackClick?: () => void
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

export function GlobalHeader({
  missionName,
  version,
  page, plugins, onPluginClick, onBackClick,
  onLogsClick, onConfigClick, onHelpClick,
  session,
}: GlobalHeaderProps) {
  const [isFullscreen, setIsFullscreen] = useState(!!document.fullscreenElement)
  const [now, setNow] = useState(new Date())
  const [elapsed, setElapsed] = useState(() => formatElapsed(session?.startedAt ?? ''))

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const onChange = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  useEffect(() => {
    if (!session?.startedAt) return
    setElapsed(formatElapsed(session.startedAt))
    const id = setInterval(() => setElapsed(formatElapsed(session.startedAt)), 30_000)
    return () => clearInterval(id)
  }, [session?.startedAt])

  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen()
    else document.documentElement.requestFullscreen()
  }
  const utcDate = now.toISOString().slice(0, 10)
  const utcTime = now.toISOString().slice(11, 19)
  const localDate = now.toLocaleDateString('en-CA')
  const localTime = now.toLocaleTimeString('en-GB', { hour12: false })
  const tz = (Intl.DateTimeFormat().resolvedOptions().timeZone.split('/').pop() ?? 'local').replace(/_/g, ' ')

  const activePlugin = page && plugins ? plugins.find(p => p.id === page) : null

  const isUntitled = !session?.tag || session.tag === 'untitled'
  const sessionLabel = isUntitled
    ? `untitled @ ${extractTimeLocal(session?.startedAt ?? '')}`
    : session?.tag ?? ''

  return (
    <header className="flex items-center h-9 px-4 shrink-0" style={{ backgroundColor: colors.bgApp }}>
      {/* Back button when on plugin page */}
      {page && onBackClick ? (
        <Button variant="ghost" size="sm" onClick={onBackClick} className="h-7 px-2 gap-1.5 text-[11px] mr-2" style={{ color: colors.dim }}>
          <ArrowLeft className="size-3.5" />
          Back
        </Button>
      ) : null}

      {/* Brand */}
      <div className="usc-brand flex items-center gap-2 mr-4 cursor-default">
        <Satellite className="usc-icon size-4 transition-colors" style={{ color: colors.label }} />
        <span className="usc-maveric font-bold text-sm tracking-wide transition-colors" style={{ color: colors.value }}>{missionName}</span>
        <span className="usc-gss font-bold text-sm tracking-wide transition-colors" style={{ color: colors.value }}>GSS</span>
        <span className="text-[11px]" style={{ color: colors.dim }}>v{version}</span>
        {activePlugin && (
          <>
            <span className="text-[11px]" style={{ color: colors.sep }}>/</span>
            <span className="text-[11px] font-medium" style={{ color: colors.label }}>{activePlugin.name}</span>
          </>
        )}
      </div>

      {/* Session info — inline separator + tag + elapsed + controls */}
      {session && (
        <div className="flex items-center gap-2">
          <span style={{ color: colors.borderStrong, fontSize: '11px', userSelect: 'none' }}>|</span>
          <span
            className="font-mono"
            style={{
              fontSize: '11px',
              color: isUntitled ? colors.textMuted : colors.textSecondary,
              fontStyle: isUntitled ? 'italic' : 'normal',
            }}
          >
            {sessionLabel}
          </span>
          {elapsed && (
            <span style={{ fontSize: '11px', color: colors.textMuted }}>{elapsed}</span>
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

      {/* Clock */}
      <div className="flex items-center gap-3 ml-auto mr-3 tabular-nums text-[11px]">
        <span style={{ color: colors.value }}>{localDate} {localTime} <span className="font-light" style={{ color: colors.dim }}>{tz}</span></span>
        <span className="font-light" style={{ color: colors.dim }}>{utcDate} {utcTime} UTC</span>
      </div>

      {/* Nav buttons */}
      <div className="flex items-center gap-0.5">
        {/* Plugin buttons — shown when not on a plugin page */}
        {!page && plugins && plugins.length > 0 && plugins.map(p => (
          <Button
            key={p.id}
            variant="ghost"
            size="sm"
            onClick={() => onPluginClick?.(p.id)}
            className="h-7 px-2 gap-1.5 text-[11px]"
            style={{ color: colors.dim }}
          >
            <Camera className="size-3.5" />
            {p.name}
          </Button>
        ))}
        {!page && (
          <>
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
          </>
        )}
        <Button variant="ghost" size="icon" onClick={toggleFullscreen} className="size-7 btn-feedback" title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
          {isFullscreen
            ? <Minimize className="size-3.5" style={{ color: colors.dim }} />
            : <Maximize className="size-3.5" style={{ color: colors.dim }} />
          }
        </Button>
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
  const [renameTag, setRenameTag] = useState(session.tag)
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
