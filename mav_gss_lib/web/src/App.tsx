import { useState, useEffect, useCallback, useMemo, lazy, Suspense } from 'react'
import { colors } from '@/lib/colors'
import { GlobalHeader } from '@/components/layout/GlobalHeader'
import { SplitPane } from '@/components/layout/SplitPane'
import { useRxSocket } from '@/hooks/useRxSocket'
import { useTxSocket } from '@/hooks/useTxSocket'
import { RxPanel } from '@/components/rx/RxPanel'
import { TxPanel } from '@/components/tx/TxPanel'
import { KeyboardHintBar } from '@/components/layout/KeyboardHintBar'
import { showToast } from '@/components/shared/StatusToast'
import { Toaster } from '@/components/ui/sonner'
import { Skeleton } from '@/components/ui/skeleton'
import { AlarmStrip } from '@/components/shared/AlarmStrip'
import { PromptDialog } from '@/components/shared/PromptDialog'
import type { GssConfig } from '@/lib/types'
import { authFetch } from '@/lib/auth'

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

/** Check if app is running in a pop-out panel mode */
function getPanelMode(): 'tx' | 'rx' | null {
  const params = new URLSearchParams(window.location.search)
  const panel = params.get('panel')
  if (panel === 'tx') return 'tx'
  if (panel === 'rx') return 'rx'
  return null
}

export default function App() {
  const panelMode = useMemo(() => getPanelMode(), [])
  const rx = useRxSocket()
  const columns = rx.columns
  const tx = useTxSocket()

  const [config, setConfig] = useState<GssConfig | null>(null)
  const [showLogs, setShowLogs] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const [showCommand, setShowCommand] = useState(false)
  const [replaySession, setReplaySession] = useState<string | null>(null)
  const [confirmSendSignal, setConfirmSendSignal] = useState(0)
  const [confirmClearSignal, setConfirmClearSignal] = useState(0)
  const [sessionPrompt, setSessionPrompt] = useState<'new' | 'tag' | null>(null)

  const startReplay = useCallback((sessionId: string) => {
    rx.enterReplay()
    setReplaySession(sessionId)
  }, [rx])

  const stopReplay = useCallback(() => {
    rx.exitReplay()
    setReplaySession(null)
  }, [rx])

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault()
      setShowCommand(v => !v)
      return
    }
    if (e.ctrlKey && e.key === 's') {
      e.preventDefault()
      if (tx.queue.length > 0 && !tx.sendProgress) tx.sendAll()
      return
    }
    if (e.ctrlKey && e.key === 'z') {
      e.preventDefault()
      tx.undoLast()
      return
    }
    if (e.ctrlKey && e.key === 'x') {
      e.preventDefault()
      tx.clearQueue()
      return
    }
    if (e.key === 'Escape') {
      if (showConfig) { setShowConfig(false); return }
      if (showLogs) { setShowLogs(false); return }
      if (showHelp) { setShowHelp(false); return }
      if (tx.sendProgress) { tx.abortSend(); return }
      return
    }
    if (e.key === '?' && !isInputFocused()) {
      setShowHelp((v) => !v)
      return
    }
  }, [showConfig, showLogs, showHelp, tx])

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data: GssConfig) => setConfig(data))
      .catch(() => {})
  }, [])

  // Show TX errors as toasts
  useEffect(() => {
    if (tx.error) showToast(tx.error, 'error', 'tx')
  }, [tx.error])

  // Show RX CRC failures as toasts
  useEffect(() => {
    if (rx.packets.length === 0) return
    const last = rx.packets[rx.packets.length - 1]
    if (last.crc16_ok === false) showToast(`CRC-16 FAIL: ${last.cmd || 'unknown'} #${last.num} — verify link quality`, 'warning', 'rx')
  }, [rx.packets.length])

  const version = config?.general?.version ?? '...'
  const missionName = config?.general?.mission_name ?? 'Mission'
  const uplinkMode = config?.tx?.uplink_mode ?? ''

  useEffect(() => {
    document.title = `${missionName} GSS`
  }, [missionName])

  // Pop-out: TX only
  if (panelMode === 'tx') {
    return (
      <div className="flex flex-col h-full p-2" style={{ backgroundColor: colors.bgApp }}>
        <TxPanel
          config={config}
          queue={tx.queue} summary={tx.summary} history={tx.history}
          sendProgress={tx.sendProgress} guardConfirm={tx.guardConfirm}
          uplinkMode={uplinkMode} connected={tx.connected}
          queueCommand={tx.queueCommand} queueBuilt={tx.queueBuilt}
          deleteItem={tx.deleteItem} clearQueue={tx.clearQueue}
          undoLast={tx.undoLast} toggleGuard={tx.toggleGuard}
          reorder={tx.reorder} addDelay={tx.addDelay}
          editDelay={tx.editDelay} sendAll={tx.sendAll}
          abortSend={tx.abortSend} approveGuard={tx.approveGuard}
          rejectGuard={tx.rejectGuard}
          triggerConfirmSend={confirmSendSignal}
          triggerConfirmClear={confirmClearSignal}
        />
      </div>
    )
  }

  // Pop-out: RX only
  if (panelMode === 'rx') {
    return (
      <div className="flex flex-col h-full p-2" style={{ backgroundColor: colors.bgApp }}>
        <RxPanel
          config={config}
          packets={rx.packets} status={rx.status}
          packetStats={rx.stats}
          columns={columns}
          replayMode={rx.replayMode}
          replaySession={replaySession}
          replacePackets={rx.replacePackets}
          onStopReplay={stopReplay}
        />
      </div>
    )
  }

  // Normal split layout
  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: colors.bgApp }}>
      <GlobalHeader
        missionName={missionName}
        version={version}
        onLogsClick={() => setShowLogs((v) => !v)}
        onConfigClick={() => setShowConfig((v) => !v)}
        onHelpClick={() => setShowHelp((v) => !v)}
      />
      <AlarmStrip status={rx.status} packets={rx.packets} replayMode={rx.replayMode} />
      <div className="flex-1 overflow-hidden p-4">
        <SplitPane
          left={
            <TxPanel
              config={config}
              queue={tx.queue} summary={tx.summary} history={tx.history}
              sendProgress={tx.sendProgress} guardConfirm={tx.guardConfirm}
              uplinkMode={uplinkMode} connected={tx.connected}
              queueCommand={tx.queueCommand} queueBuilt={tx.queueBuilt}
              deleteItem={tx.deleteItem} clearQueue={tx.clearQueue}
              undoLast={tx.undoLast} toggleGuard={tx.toggleGuard}
              reorder={tx.reorder} addDelay={tx.addDelay}
              editDelay={tx.editDelay} sendAll={tx.sendAll}
              abortSend={tx.abortSend} approveGuard={tx.approveGuard}
              rejectGuard={tx.rejectGuard}
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
            />
          }
        />
      </div>
      {showConfig && (
        <Suspense fallback={<ConfigSidebarSkeleton />}>
          <ConfigSidebar open={showConfig} onClose={() => { setShowConfig(false); fetch('/api/config').then(r => r.json()).then(setConfig) }} />
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
              toggleHex: () => {},
              toggleUplink: () => {},
              toggleFrame: () => {},
              toggleWrapper: () => {},
              openConfig: () => setShowConfig(true),
              openLogs: () => setShowLogs(true),
              openHelp: () => setShowHelp(true),
              newSession: () => setSessionPrompt('new'),
              tagSession: () => setSessionPrompt('tag'),
            }}
          />
        </Suspense>
      )}
      <KeyboardHintBar />
      {sessionPrompt === 'new' && (
        <PromptDialog
          open
          title="New Log Session"
          placeholder="Session tag (optional)"
          onSubmit={(tag) => {
            setSessionPrompt(null)
            authFetch('/api/logs/new', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ tag }),
            }).then(r => r.json()).then(d => {
              if (d.ok) showToast('New log session started', 'success')
            }).catch(() => showToast('Failed to start new session', 'error'))
          }}
          onCancel={() => setSessionPrompt(null)}
        />
      )}
      {sessionPrompt === 'tag' && (
        <PromptDialog
          open
          title="Tag Session"
          placeholder="Tag name"
          required
          onSubmit={(tag) => {
            setSessionPrompt(null)
            authFetch('/api/logs/tag', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ tag }),
            }).then(r => r.json()).then(d => {
              if (d.ok) showToast(`Session tagged: ${tag}`, 'success')
            }).catch(() => showToast('Failed to tag session', 'error'))
          }}
          onCancel={() => setSessionPrompt(null)}
        />
      )}
      <Toaster position="top-center" />
    </div>
  )
}
