import { useState, useEffect, useCallback, useMemo, useRef, lazy, Suspense } from 'react'
import { useShortcuts, type Shortcut } from '@/hooks/useShortcuts'
import { GlobalHeader } from '@/components/layout/GlobalHeader'
import { SplitPane } from '@/components/layout/SplitPane'
import { useAppRx, useAppTx, useAppSession } from '@/hooks/useAppContext'
import { RxPanel } from '@/components/rx/RxPanel'
import { TxPanel } from '@/components/tx/TxPanel'
import { KeyboardHintBar } from '@/components/layout/KeyboardHintBar'
import { showToast } from '@/components/shared/StatusToast'
import { AlarmStrip } from '@/components/shared/AlarmStrip'
import { Skeleton } from '@/components/ui/skeleton'
import type { GssConfig } from '@/lib/types'
import type { PluginPageDef } from '@/plugins/registry'
import { SessionBar } from '@/components/layout/SessionBar'

const ConfigSidebar = lazy(() => import('@/components/config/ConfigSidebar').then((m) => ({ default: m.ConfigSidebar })))
const LogViewer = lazy(() => import('@/components/logs/LogViewer').then((m) => ({ default: m.LogViewer })))
const HelpModal = lazy(() => import('@/components/shared/HelpModal').then((m) => ({ default: m.HelpModal })))
const CommandPalette = lazy(() => import('@/components/shared/CommandPalette').then((m) => ({ default: m.CommandPalette })))

function ConfigSidebarSkeleton() {
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

function LogViewerSkeleton() {
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

function HelpModalSkeleton() {
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

function CommandPaletteSkeleton() {
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

function isInputFocused(): boolean {
  const tag = document.activeElement?.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' ||
    (document.activeElement as HTMLElement)?.isContentEditable === true
}

interface MainDashboardProps {
  config: GssConfig | null
  onConfigChange: (cfg: GssConfig) => void
  missionName: string
  version: string
  plugins: PluginPageDef[]
  onPluginClick: (id: string) => void
}

export function MainDashboard({ config, onConfigChange, missionName, version, plugins, onPluginClick }: MainDashboardProps) {
  const rx = useAppRx()
  const columns = rx.columns
  const tx = useAppTx()
  const session = useAppSession()

  const [showLogs, setShowLogs] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const [showCommand, setShowCommand] = useState(false)
  const [replaySession, setReplaySession] = useState<string | null>(null)
  const [confirmSendSignal, setConfirmSendSignal] = useState(0)
  const [confirmClearSignal, setConfirmClearSignal] = useState(0)
  const [rxShowHex, setRxShowHex] = useState(false)
  const [rxShowFrame, setRxShowFrame] = useState(false)
  const [rxShowWrapper, setRxShowWrapper] = useState(false)
  const [rxHideUplink, setRxHideUplink] = useState(true)

  const startReplay = useCallback((sessionId: string) => {
    rx.enterReplay()
    setReplaySession(sessionId)
  }, [rx])

  const stopReplay = useCallback(() => {
    rx.exitReplay()
    setReplaySession(null)
  }, [rx])

  const shortcuts = useMemo<Shortcut[]>(() => [
    { key: 'k', ctrl: true, action: () => setShowCommand(v => !v) },
    { key: 's', ctrl: true, action: () => { if (tx.queue.length > 0 && !tx.sendProgress) tx.sendAll() } },
    { key: 'z', ctrl: true, action: () => tx.undoLast() },
    { key: 'x', ctrl: true, action: () => tx.clearQueue() },
    { key: 'Escape', action: () => setShowConfig(false), when: () => showConfig },
    { key: 'Escape', action: () => setShowLogs(false), when: () => showLogs },
    { key: 'Escape', action: () => setShowHelp(false), when: () => showHelp },
    { key: 'Escape', action: () => tx.abortSend(), when: () => !!tx.sendProgress },
    { key: '?', action: () => setShowHelp(v => !v), when: () => !isInputFocused() },
  ], [showConfig, showLogs, showHelp, tx])

  useShortcuts(shortcuts)

  // Show TX errors as toasts
  useEffect(() => {
    if (tx.error) showToast(tx.error, 'error', 'tx')
  }, [tx.error])

  // Show RX CRC failures as toasts
  const lastCrcCheckedNum = useRef(-1)
  useEffect(() => {
    if (rx.packets.length === 0) return
    const last = rx.packets[rx.packets.length - 1]
    if (last.num <= lastCrcCheckedNum.current) return
    lastCrcCheckedNum.current = last.num
    const flags = last._rendering?.row?.values?.flags
    const hasCrcFail = Array.isArray(flags) && flags.some(
      (f: unknown) => typeof f === 'object' && f !== null && (f as Record<string, string>).tag === 'CRC',
    )
    const cmdLabel = String(last._rendering?.row?.values?.cmd ?? 'unknown').split(' ')[0] || 'unknown'
    if (hasCrcFail) showToast(`CRC-16 FAIL: ${cmdLabel} #${last.num} — verify link quality`, 'warning', 'rx')
  }, [rx.packets])

  const uplinkMode = config?.tx?.uplink_mode ?? ''

  return (
    <>
      <GlobalHeader
        missionName={missionName}
        version={version}
        plugins={plugins}
        onPluginClick={onPluginClick}
        onLogsClick={() => setShowLogs(v => !v)}
        onConfigClick={() => setShowConfig(v => !v)}
        onHelpClick={() => setShowHelp(v => !v)}
      />
      <SessionBar {...session} />
      <AlarmStrip status={rx.status} packets={rx.packets} replayMode={rx.replayMode} sessionResetGen={rx.sessionResetGen} />
      <div className="flex-1 overflow-hidden p-4">
        <SplitPane
          left={
            <TxPanel
              config={config}
              queue={tx.queue} summary={tx.summary} history={tx.history}
              sendProgress={tx.sendProgress} guardConfirm={tx.guardConfirm}
              uplinkMode={uplinkMode} connected={tx.connected}
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
            <RxPanel
              config={config}
              packets={rx.packets} status={rx.status}
              packetStats={rx.stats}
              columns={columns}
              replayMode={rx.replayMode}
              replaySession={replaySession}
              replacePackets={rx.replacePackets}
              onStopReplay={stopReplay}
              sessionResetGen={rx.sessionResetGen}
              sessionTag={rx.sessionResetTag || session.tag}
              externalShowHex={rxShowHex}
              externalShowFrame={rxShowFrame}
              externalShowWrapper={rxShowWrapper}
              externalHideUplink={rxHideUplink}
              onToggleHex={() => setRxShowHex(v => !v)}
              onToggleFrame={() => setRxShowFrame(v => !v)}
              onToggleWrapper={() => setRxShowWrapper(v => !v)}
              onToggleUplink={() => setRxHideUplink(v => !v)}
            />
          }
        />
      </div>
      {showConfig && (
        <Suspense fallback={<ConfigSidebarSkeleton />}>
          <ConfigSidebar open={showConfig} onClose={() => { setShowConfig(false); fetch('/api/config').then(r => r.json()).then(onConfigChange) }} />
        </Suspense>
      )}
      {showLogs && (
        <Suspense fallback={<LogViewerSkeleton />}>
          <LogViewer open={showLogs} onClose={() => setShowLogs(false)} onStartReplay={startReplay} />
        </Suspense>
      )}
      {showHelp && (
        <Suspense fallback={<HelpModalSkeleton />}>
          <HelpModal open={showHelp} onClose={() => setShowHelp(false)} />
        </Suspense>
      )}
      {showCommand && (
        <Suspense fallback={<CommandPaletteSkeleton />}>
          <CommandPalette
            open={showCommand}
            onOpenChange={setShowCommand}
            actions={{
              confirmSend: () => setConfirmSendSignal(n => n + 1),
              confirmClear: () => setConfirmClearSignal(n => n + 1),
              undoLast: tx.undoLast,
              abortSend: tx.abortSend,
              toggleHex: () => setRxShowHex(v => !v),
              toggleUplink: () => setRxHideUplink(v => !v),
              toggleFrame: () => setRxShowFrame(v => !v),
              toggleWrapper: () => setRxShowWrapper(v => !v),
              openConfig: () => setShowConfig(true),
              openLogs: () => setShowLogs(true),
              openHelp: () => setShowHelp(true),
              newSession: () => session.setOpenNewSession(true),
              tagSession: () => session.setOpenRename(true),
            }}
          />
        </Suspense>
      )}
      <KeyboardHintBar />
    </>
  )
}
