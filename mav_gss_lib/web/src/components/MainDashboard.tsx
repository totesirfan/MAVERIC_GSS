import { useEffect, useMemo, useRef, type ComponentProps } from 'react'
import { useShortcuts, type Shortcut } from '@/hooks/useShortcuts'
import { SplitPane } from '@/components/layout/SplitPane'
import { useRxStatus, useRxPackets, useRxStats, useRxDisplayToggles } from '@/state/rx'
import { useTx } from '@/state/tx'
import { useSessionContext } from '@/state/session'
import { useTabActive } from '@/components/layout/TabActiveContext'
import { RxPanel } from '@/components/rx/RxPanel'
import { TxPanel } from '@/components/tx/TxPanel'
import { showToast } from '@/components/shared/StatusToast'
import { Skeleton } from '@/components/ui/skeleton'
import { renderingFlags, renderingText } from '@/lib/rendering'
import type { GssConfig } from '@/lib/types'

/** Sentinel that watches the packet stream for CRC failures and toasts them.
 *  Rendered at the dashboard root so only this tiny node rerenders per flush. */
export function RxCrcToastSentinel() {
  const packets = useRxPackets()
  const lastCheckedNum = useRef(-1)
  useEffect(() => {
    if (packets.length === 0) return
    const last = packets[packets.length - 1]
    if (last.num <= lastCheckedNum.current) return
    lastCheckedNum.current = last.num
    const hasCrcFail = renderingFlags(last._rendering).some(f => f.tag === 'CRC')
    const cmdLabel = renderingText(last._rendering, 'cmd').split(' ')[0] || 'unknown'
    if (hasCrcFail) showToast(`CRC-16 FAIL: ${cmdLabel} #${last.num} — verify link quality`, 'warning', 'rx')
  }, [packets])
  return null
}

/** Wraps RxPanel with packets + stats subscriptions, keeping RxPanel's API unchanged. */
function RxPanelWithPackets(props: Omit<ComponentProps<typeof RxPanel>, 'packets' | 'packetStats'>) {
  const packets = useRxPackets()
  const stats = useRxStats()
  return <RxPanel {...props} packets={packets} packetStats={stats} />
}

// Lazy-load skeletons are kept here for the Suspense fallbacks used at the shell level
export function ConfigSidebarSkeleton() {
  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/70" />
      <div className="w-96 h-full p-4 border-l bg-card shadow-overlay border-border">
        <div className="flex items-center justify-between mb-4">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-6 w-6 rounded-sm" />
        </div>
        <div className="space-y-4">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </div>
    </div>
  )
}

export function LogViewerSkeleton() {
  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex flex-1 m-4 rounded-lg border overflow-hidden shadow-overlay bg-card border-border">
        <div className="w-72 shrink-0 border-r p-3 space-y-3 border-border">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="h-52 w-full" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
        <div className="flex-1 p-3 space-y-3">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      </div>
    </div>
  )
}

export function HelpModalSkeleton() {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="w-[640px] max-h-[80vh] rounded-lg border p-5 shadow-overlay bg-card border-border">
        <div className="flex items-center justify-between mb-4">
          <Skeleton className="h-5 w-44" />
          <Skeleton className="h-6 w-6 rounded-sm" />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Skeleton className="h-36 w-full" />
          <Skeleton className="h-36 w-full" />
          <Skeleton className="h-36 w-full" />
          <Skeleton className="h-36 w-full" />
        </div>
      </div>
    </div>
  )
}

export function CommandPaletteSkeleton() {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]">
      <div className="absolute inset-0 bg-black/70" />
      <div className="relative z-10 w-[480px] rounded-xl overflow-hidden border shadow-overlay p-3 space-y-3 bg-card border-border">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    </div>
  )
}

interface MainDashboardProps {
  config: GssConfig | null
  confirmSendSignal: number
  confirmClearSignal: number
  replaySession: string | null
  onStopReplay: () => void
}

export function MainDashboard({ config, confirmSendSignal, confirmClearSignal, replaySession, onStopReplay }: MainDashboardProps) {
  const rx = useRxStatus()
  const columns = rx.columns
  const tx = useTx()
  const session = useSessionContext()
  const tabActive = useTabActive()
  const rxToggles = useRxDisplayToggles()

  const shortcuts = useMemo<Shortcut[]>(() => [
    { key: 's', ctrl: true, action: () => { if (tx.queue.length > 0 && !tx.sendProgress) tx.sendAll() } },
    { key: 'z', ctrl: true, action: () => tx.undoLast() },
    { key: 'x', ctrl: true, action: () => tx.clearQueue() },
    { key: 'Escape', action: () => tx.abortSend(), when: () => !!tx.sendProgress },
  ], [tx])

  useShortcuts(shortcuts, tabActive)

  // Show TX errors as toasts
  useEffect(() => {
    if (tx.error) showToast(tx.error, 'error', 'tx')
  }, [tx.error])

  return (
    <div className="flex-1 overflow-hidden p-4">
      <SplitPane
        left={
          <TxPanel
            config={config}
            queue={tx.queue} summary={tx.summary}
            sendProgress={tx.sendProgress} guardConfirm={tx.guardConfirm}
            connected={tx.connected}
            queueCommand={tx.queueCommand}
            deleteItem={tx.deleteItem} clearQueue={tx.clearQueue}
            undoLast={tx.undoLast} toggleGuard={tx.toggleGuard}
            reorder={tx.reorder} addDelay={tx.addDelay}
            editDelay={tx.editDelay} sendAll={tx.sendAll}
            abortSend={tx.abortSend} approveGuard={tx.approveGuard}
            rejectGuard={tx.rejectGuard}
            queueTemplate={tx.queueMissionCmd}
            triggerConfirmSend={confirmSendSignal}
            triggerConfirmClear={confirmClearSignal}
          />
        }
        right={
          <RxPanelWithPackets
            config={config}
            status={rx.status}
            columns={columns}
            replayMode={rx.replayMode}
            replaySession={replaySession}
            replacePackets={rx.replacePackets}
            onStopReplay={onStopReplay}
            sessionGeneration={rx.sessionGeneration}
            sessionTag={rx.sessionTag || session.sessionTag}
            blackoutUntil={rx.blackoutUntil}
            externalShowHex={rxToggles.showHex}
            externalShowFrame={rxToggles.showFrame}
            externalShowWrapper={rxToggles.showWrapper}
            externalHideUplink={rxToggles.hideUplink}
            onToggleHex={rxToggles.toggleHex}
            onToggleFrame={rxToggles.toggleFrame}
            onToggleWrapper={rxToggles.toggleWrapper}
            onToggleUplink={rxToggles.toggleUplink}
          />
        }
      />
    </div>
  )
}
