import { useState, useEffect, useRef, useCallback } from 'react'
import { colors } from '@/lib/colors'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import type { SessionState } from '@/hooks/useSession'

function formatElapsed(startedAt: string): string {
  if (!startedAt) return ''
  const start = new Date(startedAt).getTime()
  if (isNaN(start)) return ''
  const diffMs = Date.now() - start
  if (diffMs < 0) return 'just now'
  const s = Math.floor(diffMs / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ${m % 60}m ago`
  const d = Math.floor(h / 24)
  return `${d}d ${h % 24}h ago`
}

function extractTimeLocal(startedAt: string): string {
  if (!startedAt) return ''
  const d = new Date(startedAt)
  if (isNaN(d.getTime())) return ''
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  return `${h}:${m}`
}

export function SessionBar(props: SessionState) {
  const {
    tag, startedAt, isTrafficActive,
    openNewSession, openRename,
    setOpenNewSession, setOpenRename,
    startNewSession, renameSession,
  } = props

  const [elapsed, setElapsed] = useState(() => formatElapsed(startedAt))
  const [newTag, setNewTag] = useState('')
  const [renameTag, setRenameTag] = useState(tag)
  const [showConfirm, setShowConfirm] = useState(false)
  const [confirmInput, setConfirmInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const newInputRef = useRef<HTMLInputElement>(null)
  const renameInputRef = useRef<HTMLInputElement>(null)

  // Update elapsed every 30s
  useEffect(() => {
    setElapsed(formatElapsed(startedAt))
    const id = setInterval(() => setElapsed(formatElapsed(startedAt)), 30_000)
    return () => clearInterval(id)
  }, [startedAt])

  // Sync renameTag when tag changes externally
  useEffect(() => { setRenameTag(tag) }, [tag])

  // Focus inputs when popovers open
  useEffect(() => {
    if (openNewSession) {
      setNewTag('')
      setTimeout(() => newInputRef.current?.focus(), 50)
    }
  }, [openNewSession])

  useEffect(() => {
    if (openRename) {
      setRenameTag(tag)
      setTimeout(() => renameInputRef.current?.focus(), 50)
    }
  }, [openRename, tag])

  const handleNewSubmit = useCallback(() => {
    setShowConfirm(true)
    setConfirmInput('')
    setError(null)
  }, [])

  const handleConfirm = useCallback(async () => {
    const err = await startNewSession(newTag.trim())
    if (err) {
      setError(err)
      return
    }
    setShowConfirm(false)
    setOpenNewSession(false)
  }, [newTag, startNewSession, setOpenNewSession])

  const handleRenameSubmit = useCallback(async () => {
    const err = await renameSession(renameTag.trim())
    if (err) {
      setError(err)
      return
    }
    setOpenRename(false)
  }, [renameTag, renameSession, setOpenRename])

  const isUntitled = tag === 'untitled' || !tag
  const canConfirm = isTrafficActive ? confirmInput === 'NEW' : true

  return (
    <div
      className="h-7 flex items-center gap-2.5 px-4 shrink-0"
      style={{
        backgroundColor: colors.bgApp,
        borderBottom: `1px solid ${colors.borderSubtle}`,
      }}
    >
      {/* SESSION label */}
      <span
        style={{
          fontSize: '11px',
          fontFamily: 'Inter, sans-serif',
          color: colors.textMuted,
          letterSpacing: '0.8px',
          textTransform: 'uppercase',
          userSelect: 'none',
        }}
      >
        SESSION
      </span>

      {/* Tag text */}
      <span
        style={{
          fontSize: '12px',
          fontFamily: "'JetBrains Mono', monospace",
          color: isUntitled ? colors.textMuted : colors.textSecondary,
          fontStyle: isUntitled ? 'italic' : 'normal',
        }}
      >
        {isUntitled ? `untitled @ ${extractTimeLocal(startedAt)}` : tag}
      </span>

      {/* Elapsed time */}
      {elapsed && (
        <span
          style={{
            fontSize: '11px',
            fontFamily: 'Inter, sans-serif',
            color: colors.textMuted,
          }}
        >
          {elapsed}
        </span>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* + New Session button */}
      <Popover open={openNewSession} onOpenChange={setOpenNewSession}>
        <PopoverTrigger
          className="flex items-center gap-1 px-2 py-0.5 rounded border cursor-pointer"
          style={{
            fontSize: '11px',
            fontFamily: 'Inter, sans-serif',
            color: colors.info,
            borderColor: colors.borderStrong,
            backgroundColor: colors.bgPanelRaised,
          }}
        >
          + New Session
        </PopoverTrigger>
        <PopoverContent
          align="end"
          className="w-64"
          style={{ backgroundColor: colors.bgPanelRaised, borderColor: colors.borderStrong }}
        >
          <form
            onSubmit={(e) => { e.preventDefault(); handleNewSubmit() }}
            className="flex flex-col gap-2"
          >
            <Input
              ref={newInputRef}
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
            <button
              type="submit"
              className="self-end px-3 py-1 rounded text-[11px] font-medium border"
              style={{
                color: colors.info,
                borderColor: colors.borderStrong,
                backgroundColor: colors.bgPanelRaised,
              }}
            >
              Start
            </button>
          </form>
        </PopoverContent>
      </Popover>

      {/* Confirm Dialog */}
      <Dialog open={showConfirm} onOpenChange={setShowConfirm}>
        <DialogContent
          showCloseButton={false}
          style={{ backgroundColor: colors.bgPanelRaised, borderColor: colors.borderStrong }}
        >
          <DialogHeader>
            <DialogTitle style={{ color: colors.warning }}>
              Start New Session?
            </DialogTitle>
            <DialogDescription style={{ color: colors.textSecondary, fontSize: '12px' }}>
              This will rotate logs and clear the packet list. TX queue and images are preserved.
            </DialogDescription>
          </DialogHeader>

          {isTrafficActive && (
            <div
              className="flex flex-col gap-2 rounded px-3 py-2"
              style={{
                backgroundColor: colors.dangerFill,
                border: `1px solid ${colors.danger}4D`,
              }}
            >
              <span style={{ color: colors.danger, fontSize: '12px', fontWeight: 600 }}>
                &#9888; RX traffic detected
              </span>
              <Input
                placeholder='Type "NEW" to confirm'
                value={confirmInput}
                onChange={(e) => setConfirmInput(e.target.value)}
                className="h-7 text-xs"
                style={{
                  backgroundColor: colors.bgApp,
                  color: colors.textPrimary,
                  borderColor: colors.borderSubtle,
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              />
            </div>
          )}

          {error && (
            <div className="text-xs px-3 py-2 rounded" style={{ color: colors.danger, backgroundColor: colors.dangerFill }}>
              {error}
            </div>
          )}

          <DialogFooter>
            <button
              onClick={() => setShowConfirm(false)}
              className="px-3 py-1.5 rounded text-xs"
              style={{ color: colors.textMuted }}
            >
              Cancel
            </button>
            <button
              onClick={handleConfirm}
              disabled={!canConfirm}
              className="px-3 py-1.5 rounded text-xs font-medium disabled:opacity-30"
              style={{
                backgroundColor: colors.warningFill,
                color: colors.warning,
                border: `1px solid ${colors.warning}4D`,
              }}
            >
              Confirm
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Caret dropdown */}
      <DropdownMenu>
        <DropdownMenuTrigger
          className="flex items-center justify-center px-1 py-0.5 rounded border cursor-pointer"
          style={{
            fontSize: '9px',
            color: colors.textMuted,
            borderColor: colors.borderStrong,
            backgroundColor: colors.bgPanelRaised,
          }}
        >
          &#9660;
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => { setOpenRename(true); setError(null) }}>
            Rename Session
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Rename Dialog (separate from dropdown to avoid anchor issues) */}
      <Dialog open={openRename} onOpenChange={(v) => { setOpenRename(v); if (!v) setError(null) }}>
        <DialogContent
          showCloseButton={false}
          style={{ backgroundColor: colors.bgPanelRaised, borderColor: colors.borderStrong }}
        >
          <DialogHeader>
            <DialogTitle style={{ color: colors.textPrimary, fontSize: '14px' }}>Rename Session</DialogTitle>
          </DialogHeader>
          <form
            onSubmit={(e) => { e.preventDefault(); handleRenameSubmit() }}
            className="flex flex-col gap-2"
          >
            {error && (
              <div className="text-xs px-2 py-1 rounded" style={{ color: colors.danger, backgroundColor: colors.dangerFill }}>
                {error}
              </div>
            )}
            <Input
              ref={renameInputRef}
              placeholder="session tag"
              value={renameTag}
              onChange={(e) => setRenameTag(e.target.value)}
              className="h-7 text-xs"
              style={{
                backgroundColor: colors.bgApp,
                color: colors.textPrimary,
                borderColor: colors.borderSubtle,
                fontFamily: "'JetBrains Mono', monospace",
              }}
            />
            <DialogFooter>
              <button
                type="button"
                onClick={() => setOpenRename(false)}
                className="px-3 py-1.5 rounded text-xs"
                style={{ color: colors.textMuted }}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-3 py-1 rounded text-[11px] font-medium border"
                style={{
                  color: colors.info,
                  borderColor: colors.borderStrong,
                  backgroundColor: colors.bgPanelRaised,
                }}
              >
                Save
              </button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
