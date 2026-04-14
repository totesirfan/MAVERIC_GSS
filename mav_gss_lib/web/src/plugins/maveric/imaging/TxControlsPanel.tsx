import { useState, useEffect, useRef } from 'react'
import { Send, StopCircle } from 'lucide-react'
import { motion } from 'framer-motion'
import { Button } from '@/components/ui/button'
import { GssInput } from '@/components/ui/gss-input'
import { ConfirmBar } from '@/components/shared/ConfirmBar'
import { showToast } from '@/components/shared/StatusToast'
import { colors } from '@/lib/colors'
import { FilenameInput } from './FilenameInput'
import { withJpg, DEFAULT_DEST_ARG, DEFAULT_CHUNK_SIZE } from './helpers'
import type { SendProgress, GuardConfirm } from '@/lib/types'

export interface PendingCmd {
  cmdId: string
  args: Record<string, string>
  label: string
  destNode: string
}

interface TxControlsPanelProps {
  nodes: string[]
  destNode: string
  onDestNodeChange: (n: string) => void

  /** Filename of the currently-selected file in the progress panel; auto-fills Get Chunk form. */
  suggestedFilename?: string
  /** Known total chunk count for `suggestedFilename`; fills start=0 / count=total in the Get Chunk form. */
  suggestedTotal?: number | null

  stageCommand: (cmdId: string, args: Record<string, string>, label: string) => void

  pendingCmd: PendingCmd | null
  onConfirmSend: () => void
  onCancelPending: () => void

  sendProgress: SendProgress | null
  onAbort: () => void

  guardConfirm: GuardConfirm | null
  onApproveGuard: () => void
  onRejectGuard: () => void
}

/**
 * TX Controls card for the imaging page. Owns its own form state and
 * auto-fills the Get Chunk form when the caller provides a suggested
 * filename / known total. The card's bottom bar renders one of three
 * shared status strips (confirm / guard / send progress).
 */
export function TxControlsPanel({
  nodes, destNode, onDestNodeChange,
  suggestedFilename, suggestedTotal,
  stageCommand,
  pendingCmd, onConfirmSend, onCancelPending,
  sendProgress, onAbort,
  guardConfirm, onApproveGuard, onRejectGuard,
}: TxControlsPanelProps) {
  const [cntFilename, setCntFilename] = useState('')
  const [cntDestArg, setCntDestArg] = useState('')
  const [cntChunkSize, setCntChunkSize] = useState('')

  const [getFilename, setGetFilename] = useState('')
  const [getStartChunk, setGetStartChunk] = useState('')
  const [getNumChunks, setGetNumChunks] = useState('')
  const [getDestArg, setGetDestArg] = useState('')

  // Track the values this component last *auto-filled* into each field.
  // Auto-fill only overwrites if the current value is empty or still matches
  // the last-autofilled value, so manual edits are never clobbered.
  const autoRef = useRef({ cntFn: '', getFn: '', start: '', num: '' })

  // Auto-fill filenames when the parent points us at a file.
  // Capture the ref values into locals *before* the setState updaters run,
  // otherwise the lazy updaters would read the already-mutated ref.
  useEffect(() => {
    if (!suggestedFilename) return
    const lastCntFn = autoRef.current.cntFn
    const lastGetFn = autoRef.current.getFn
    setCntFilename(prev => (prev === '' || prev === lastCntFn) ? suggestedFilename : prev)
    setGetFilename(prev => (prev === '' || prev === lastGetFn) ? suggestedFilename : prev)
    autoRef.current.cntFn = suggestedFilename
    autoRef.current.getFn = suggestedFilename
  }, [suggestedFilename])

  // Auto-fill start/count when the total is known. Keeps manual edits.
  useEffect(() => {
    if (!suggestedFilename) return
    if (suggestedTotal == null || suggestedTotal <= 0) return
    const newStart = '0'
    const newNum = String(suggestedTotal)
    const lastStart = autoRef.current.start
    const lastNum = autoRef.current.num
    setGetStartChunk(prev => (prev === '' || prev === lastStart) ? newStart : prev)
    setGetNumChunks(prev => (prev === '' || prev === lastNum) ? newNum : prev)
    autoRef.current.start = newStart
    autoRef.current.num = newNum
  }, [suggestedFilename, suggestedTotal])

  const disableSend = !!sendProgress || !!guardConfirm || !!pendingCmd

  const handleCntChunks = () => {
    if (!cntFilename.trim()) {
      showToast('Filename required', 'error', 'tx')
      return
    }
    const fn = withJpg(cntFilename.trim())
    const dest = cntDestArg.trim() || DEFAULT_DEST_ARG
    const size = cntChunkSize.trim() || DEFAULT_CHUNK_SIZE
    stageCommand(
      'img_cnt_chunks',
      { Filename: fn, Destination: dest, 'Chunk Size': size },
      `img_cnt_chunks ${fn} target=${dest} size=${size}`,
    )
  }

  const handleGetChunk = () => {
    if (!getFilename.trim()) {
      showToast('Filename required', 'error', 'tx')
      return
    }
    const start = getStartChunk.trim()
    if (!start) {
      showToast('Start chunk required', 'error', 'tx')
      return
    }
    const fn = withJpg(getFilename.trim())
    const count = getNumChunks.trim() || '1'
    const dest = getDestArg.trim() || DEFAULT_DEST_ARG
    stageCommand(
      'img_get_chunk',
      { Filename: fn, 'Start Chunk': start, 'Num Chunks': count, Destination: dest },
      `img_get_chunk ${fn} start=${start} n=${count} target=${dest}`,
    )
  }

  return (
    <div className="rounded-lg border overflow-hidden" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}>
      <div className="flex items-center gap-2 px-3 py-1.5 border-b" style={{ borderColor: colors.borderSubtle }}>
        <Send className="size-3.5" style={{ color: colors.dim }} />
        <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.label }}>TX Controls</span>
      </div>
      <div className="p-3 space-y-3">
        {/* Routing — node on the CSP header */}
        <div>
          <div className="text-[11px] font-medium mb-1" style={{ color: colors.dim }}>Route to node</div>
          <div className="flex flex-wrap gap-1">
            {nodes.map(n => (
              <button
                key={n}
                onClick={() => onDestNodeChange(n)}
                className="px-2 py-0.5 rounded text-[11px] font-medium border"
                style={{
                  borderColor: destNode === n ? colors.label : colors.borderSubtle,
                  backgroundColor: destNode === n ? `${colors.label}18` : 'transparent',
                  color: destNode === n ? colors.label : colors.dim,
                }}
                title={`Route imaging command to ${n}`}
              >
                {n}
              </button>
            ))}
          </div>
        </div>

        {/* Count Chunks */}
        <div>
          <div className="text-[11px] font-medium mb-1" style={{ color: colors.dim }}>Count Chunks</div>
          <div className="flex gap-2">
            <FilenameInput value={cntFilename} onChange={setCntFilename} onEnter={handleCntChunks} />
            <GssInput
              className="!w-16"
              placeholder="target"
              title="Satellite-side target arg (wire value — not the routing node)"
              value={cntDestArg}
              onChange={e => setCntDestArg(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleCntChunks() }}
            />
            <GssInput
              className="!w-20"
              placeholder="chunk size"
              title={`Bytes per chunk (default ${DEFAULT_CHUNK_SIZE})`}
              value={cntChunkSize}
              onChange={e => setCntChunkSize(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleCntChunks() }}
            />
            <Button
              size="sm"
              onClick={handleCntChunks}
              disabled={disableSend}
              className="h-7 px-3 text-[11px] shrink-0"
              style={{ backgroundColor: colors.label, color: colors.bgApp }}
            >
              Send
            </Button>
          </div>
        </div>

        {/* Get Chunk */}
        <div>
          <div className="text-[11px] font-medium mb-1" style={{ color: colors.dim }}>Get Chunk</div>
          <div className="flex gap-2">
            <FilenameInput value={getFilename} onChange={setGetFilename} onEnter={handleGetChunk} />
            <GssInput
              className="!w-16"
              placeholder="start"
              title="First chunk index to request"
              value={getStartChunk}
              onChange={e => setGetStartChunk(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleGetChunk() }}
            />
            <GssInput
              className="!w-16"
              placeholder="count"
              title="Number of chunks to request starting from `start`"
              value={getNumChunks}
              onChange={e => setGetNumChunks(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleGetChunk() }}
            />
            <GssInput
              className="!w-16"
              placeholder="target"
              title="Satellite-side target arg (wire value — not the routing node)"
              value={getDestArg}
              onChange={e => setGetDestArg(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleGetChunk() }}
            />
            <Button
              size="sm"
              onClick={handleGetChunk}
              disabled={disableSend}
              className="h-7 px-3 text-[11px] shrink-0"
              style={{ backgroundColor: colors.label, color: colors.bgApp }}
            >
              Send
            </Button>
          </div>
        </div>
      </div>

      {/* Bottom status strip — confirm send / guard / send progress */}
      {pendingCmd && !guardConfirm && !sendProgress ? (
        <ConfirmBar
          label={`Send ${pendingCmd.label}?`}
          color={colors.success}
          onConfirm={onConfirmSend}
          onCancel={onCancelPending}
        />
      ) : guardConfirm ? (
        <ConfirmBar
          label={`GUARD — ${guardConfirm.display.title}${guardConfirm.display.subtitle ? ` — ${guardConfirm.display.subtitle}` : ''}`}
          color={colors.warning}
          onConfirm={onApproveGuard}
          onCancel={onRejectGuard}
        />
      ) : sendProgress ? (
        <SendProgressBar sendProgress={sendProgress} onAbort={onAbort} />
      ) : null}
    </div>
  )
}

function SendProgressBar({ sendProgress, onAbort }: { sendProgress: SendProgress; onAbort: () => void }) {
  return (
    <div
      className="flex items-center justify-between px-3 py-1.5 border-t shrink-0 relative overflow-hidden"
      style={{ borderColor: colors.info, backgroundColor: `${colors.info}18` }}
    >
      <motion.div
        className="absolute inset-y-0 left-0"
        style={{ backgroundColor: `${colors.info}22` }}
        initial={{ width: '0%' }}
        animate={{ width: `${(sendProgress.sent / Math.max(sendProgress.total, 1)) * 100}%` }}
        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      />
      <span className="text-xs font-bold truncate mr-2 relative z-10" style={{ color: colors.info }}>
        Sent {sendProgress.sent}/{sendProgress.total}
        {sendProgress.waiting ? (
          <span className="ml-1" style={{ color: colors.warning }}>— delay</span>
        ) : (
          <span className="ml-1" style={{ color: colors.dim }}>— {sendProgress.current}</span>
        )}
      </span>
      <button
        onClick={onAbort}
        className="text-[11px] px-3 py-0.5 rounded font-bold btn-feedback relative z-10 flex items-center gap-1"
        style={{ backgroundColor: colors.danger, color: colors.bgApp }}
      >
        <StopCircle className="size-3.5" /> Abort
      </button>
    </div>
  )
}
