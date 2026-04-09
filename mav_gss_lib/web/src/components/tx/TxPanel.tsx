import { useState, useMemo, Suspense } from 'react'
import { useEffect } from 'react'
import { useShortcuts } from '@/hooks/useShortcuts'
import { motion } from 'framer-motion'
import { FileUp, StopCircle, Send as SendIcon, ShieldCheck, X, ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { StatusDot } from '@/components/shared/StatusDot'
import { colors } from '@/lib/colors'
import { TxQueue } from './TxQueue'
import { SentHistory } from './SentHistory'
import { CommandInput } from './CommandInput'
import { ImportDialog } from './ImportDialog'
import { getMissionBuilder } from '@/plugins/registry'
import type {
  TxQueueItem, TxQueueSummary, TxHistoryItem,
  SendProgress, GuardConfirm, GssConfig, TxColumnDef,
} from '@/lib/types'

interface TxPanelProps {
  config: GssConfig | null
  queue: TxQueueItem[]
  summary: TxQueueSummary
  history: TxHistoryItem[]
  sendProgress: SendProgress | null
  guardConfirm: GuardConfirm | null
  uplinkMode: string
  connected: boolean
  queueCommand: (line: string) => void
  deleteItem: (index: number) => void
  clearQueue: () => void
  undoLast: () => void
  toggleGuard: (index: number) => void
  reorder: (oldIndex: number, newIndex: number) => void
  addDelay: (ms: number) => void
  editDelay: (index: number, ms: number) => void
  sendAll: () => void
  abortSend: () => void
  approveGuard: () => void
  rejectGuard: () => void
  queueTemplate: (payload: Record<string, unknown>) => void
  triggerConfirmSend?: number
  triggerConfirmClear?: number
}

export function TxPanel({
  config, queue, summary, history, sendProgress, guardConfirm, uplinkMode, connected,
  queueCommand, deleteItem, clearQueue,
  toggleGuard, reorder, editDelay, addDelay,
  sendAll, abortSend, approveGuard, rejectGuard,
  queueTemplate,
  triggerConfirmSend, triggerConfirmClear,
}: TxPanelProps) {
  const [showBuilder, setShowBuilder] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [txColumns, setTxColumns] = useState<TxColumnDef[]>([])

  const missionId = config?.general?.mission ?? ''
  /* eslint-disable react-hooks/static-components */
  const MissionBuilder = useMemo(() => getMissionBuilder(missionId), [missionId])
  const hasCommandBuilder = MissionBuilder !== null

  useEffect(() => {
    fetch('/api/tx-columns').then(r => r.json()).then(setTxColumns).catch(() => {})
  }, [])

  const sending = sendProgress !== null
  const modeColor = uplinkMode.toLowerCase().includes('golay') ? colors.frameGolay : colors.frameAx25
  const missionName = config?.general?.mission_name ?? 'Mission'

  return (
    <div className="flex flex-col h-full gap-3">
      {/* Main card — queue + optional builder split */}
      <div className="flex flex-col flex-1 min-h-0 rounded-lg border overflow-hidden shadow-panel" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}>
        {/* Panel header */}
        <div className="flex items-center justify-between px-3 py-1.5 border-b shrink-0" style={{ borderColor: colors.borderSubtle }}>
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold tracking-wide uppercase" style={{ color: colors.value }}>{config?.general?.tx_title ?? 'TX Uplink'}</span>
            <StatusDot status={connected ? 'LIVE' : 'DOWN'} />
            <span className="text-[11px] font-medium" style={{ color: modeColor }}>{uplinkMode || '--'}</span>
            {sending && (
              <Badge className="text-[11px] px-1.5 py-0 h-5 animate-pulse-text" style={{ backgroundColor: `${colors.infoFill}`, color: colors.info }}>
                SENDING {sendProgress.sent}/{sendProgress.total}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" className="size-6" onClick={() => setShowImport(true)} title="Import commands">
              <FileUp className="size-3.5" style={{ color: colors.dim }} />
            </Button>
            <Button variant="ghost" size="icon" className="size-6" onClick={() => window.open('/?panel=tx', `${missionName.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-tx`, 'popup=1,width=600,height=800')} title={`Pop out ${missionName} TX panel`}>
              <ExternalLink className="size-3.5" style={{ color: colors.dim }} />
            </Button>
          </div>
        </div>

        {/* Queue */}
        <TxQueue
          queue={queue} summary={summary} sendProgress={sendProgress} isGuarding={!!guardConfirm}
          txColumns={txColumns}
          onToggleGuard={toggleGuard} onDelete={deleteItem}
          onEditDelay={editDelay} onReorder={reorder} onAddDelay={addDelay}
          onClear={clearQueue} onSend={sendAll}
          onDuplicate={(idx) => {
            const item = queue[idx]
            if (!item || item.type !== 'mission_cmd') return
            queueTemplate(item.payload)
          }}
          onMoveToTop={(idx) => reorder(idx, queue.length - 1)}
          onMoveToBottom={(idx) => reorder(idx, 0)}
          triggerConfirmSend={triggerConfirmSend}
          triggerConfirmClear={triggerConfirmClear}
        />
      </div>

      {/* Sent history — separate collapsible block */}
      <SentHistory history={history} txColumns={txColumns} onRequeue={(item) => {
        queueTemplate(item.payload)
      }} />

      {/* Bottom block: guard confirm / send progress / input+builder */}
      {guardConfirm ? (
        <div className="shrink-0">
          <GuardConfirmBlock
            guardConfirm={guardConfirm}
            onApprove={approveGuard}
            onReject={rejectGuard}
          />
        </div>
      ) : sending ? (
        <div className="shrink-0 flex gap-2 h-[52px]">
          <div className="flex-1 rounded-lg border overflow-hidden flex items-center gap-2 px-3 relative" style={{ borderColor: `${colors.info}44`, backgroundColor: `${colors.info}08` }}>
            <motion.div
              className="absolute inset-y-0 left-0"
              style={{ backgroundColor: `${colors.info}15` }}
              initial={{ width: '0%' }}
              animate={{ width: `${(sendProgress.sent / sendProgress.total) * 100}%` }}
              transition={{ type: 'spring', stiffness: 300, damping: 30 }}
            />
            <div className="flex items-center gap-2 text-xs font-mono relative z-10">
              <SendIcon className="size-4 animate-pulse-text" style={{ color: colors.info }} />
              <span className="font-bold" style={{ color: colors.info }}>
                Sent {sendProgress.sent}/{sendProgress.total}
              </span>
              {sendProgress.waiting ? (
                <span style={{ color: colors.warning }}>— delay</span>
              ) : (
                <span style={{ color: colors.dim }}>— {sendProgress.current}</span>
              )}
            </div>
          </div>
          <button
            onClick={abortSend}
            className="flex flex-col items-center justify-center gap-0.5 w-16 rounded-lg border text-xs font-bold shrink-0 transition-colors hover:brightness-110 btn-feedback"
            style={{ borderColor: colors.error, color: colors.bgApp, backgroundColor: colors.error }}
          >
            <StopCircle className="size-4" />
            <span className="text-[11px]">Abort</span>
          </button>
        </div>
      ) : (
        <motion.div
          className="rounded-lg border overflow-hidden shadow-float"
          style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgApp }}
          animate={{ height: showBuilder ? '50vh' : 62 }}
          transition={{ type: 'spring', stiffness: 400, damping: 30, mass: 0.8 }}
        >
          {showBuilder && hasCommandBuilder && MissionBuilder ? (
            <Suspense fallback={<div className="p-4 text-xs" style={{ color: colors.dim }}>Loading builder...</div>}>
              <MissionBuilder onQueue={queueTemplate} onClose={() => setShowBuilder(false)} />
            </Suspense>
          ) : (
            <CommandInput onSubmit={queueCommand} onBuilderToggle={hasCommandBuilder && MissionBuilder ? () => setShowBuilder(true) : undefined} />
          )}
        </motion.div>
      )}

      {/* Dialogs */}
      <ImportDialog open={showImport} onClose={() => setShowImport(false)} onImported={() => {}} txColumns={txColumns} />
    </div>
  )
  /* eslint-enable react-hooks/static-components */
}

/* Guard confirm inline block */
function GuardConfirmBlock({ guardConfirm, onApprove, onReject }: {
  guardConfirm: GuardConfirm
  onApprove: () => void
  onReject: () => void
}) {
  // Enter to approve, Escape to reject
  useShortcuts([
    { key: 'Enter', action: onApprove },
    { key: 'Escape', action: onReject },
  ])

  return (
    <div
      className="rounded-lg border animate-pulse-warning h-[62px] flex overflow-hidden"
      style={{ borderColor: `${colors.warning}44` }}
    >
      {/* Info */}
      <div className="flex-1 flex items-center gap-3 px-3">
        <ShieldCheck className="size-5 shrink-0 animate-pulse-text" style={{ color: colors.warning }} />
        <div className="min-w-0">
          <div className="text-xs font-bold" style={{ color: colors.warning }}>GUARD — Confirm to send</div>
          <div className="text-[11px] truncate" style={{ color: colors.value }}>
            {guardConfirm.display.title}{guardConfirm.display.subtitle ? ` — ${guardConfirm.display.subtitle}` : ''}
          </div>
        </div>
      </div>

      {/* Reject */}
      <button
        onClick={onReject}
        className="px-3 flex items-center justify-center border-l transition-colors hover:bg-white/[0.05]"
        style={{ borderColor: colors.borderSubtle, color: colors.dim }}
      >
        <X className="size-4" />
      </button>

      {/* Approve — full height block */}
      <button
        onClick={onApprove}
        className="px-5 flex flex-col items-center justify-center gap-0.5 transition-colors hover:brightness-110 btn-feedback"
        style={{ backgroundColor: colors.warning, color: colors.bgApp }}
      >
        <ShieldCheck className="size-4" />
        <span className="text-[11px] font-bold">Confirm ↵</span>
      </button>
    </div>
  )
}
