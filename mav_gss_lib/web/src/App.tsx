import { useState, useEffect, useCallback, useMemo } from 'react'
import { colors } from '@/lib/colors'
import { GlobalHeader } from '@/components/layout/GlobalHeader'
import { SplitPane } from '@/components/layout/SplitPane'
import { useRxSocket } from '@/hooks/useRxSocket'
import { useTxSocket } from '@/hooks/useTxSocket'
import { RxPanel } from '@/components/rx/RxPanel'
import { TxPanel } from '@/components/tx/TxPanel'
import { ConfigSidebar } from '@/components/config/ConfigSidebar'
import { LogViewer } from '@/components/logs/LogViewer'
import { HelpModal } from '@/components/shared/HelpModal'
import { CommandPalette } from '@/components/shared/CommandPalette'
import { KeyboardHintBar } from '@/components/layout/KeyboardHintBar'
import { showToast } from '@/components/shared/StatusToast'
import { Toaster } from '@/components/ui/sonner'
import { useAlarms } from '@/hooks/useAlarms'
import { AlarmStrip } from '@/components/shared/AlarmStrip'
import type { GssConfig } from '@/lib/types'

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
  const tx = useTxSocket()
  const { alarms, ackAll, ackOne } = useAlarms(rx.status, rx.packets, rx.replayMode)

  const [config, setConfig] = useState<GssConfig | null>(null)
  const [showLogs, setShowLogs] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const [showCommand, setShowCommand] = useState(false)
  const [replaySession, setReplaySession] = useState<string | null>(null)
  const [confirmSendSignal, setConfirmSendSignal] = useState(0)
  const [confirmClearSignal, setConfirmClearSignal] = useState(0)

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
  const uplinkMode = config?.tx?.uplink_mode ?? ''

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
          packets={rx.packets} status={rx.status}
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
        version={version}
        onLogsClick={() => setShowLogs((v) => !v)}
        onConfigClick={() => setShowConfig((v) => !v)}
        onHelpClick={() => setShowHelp((v) => !v)}
      />
      <AlarmStrip alarms={alarms} onAckAll={ackAll} onAckOne={ackOne} />
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
              packets={rx.packets} status={rx.status}
              replayMode={rx.replayMode}
              replaySession={replaySession}
              replacePackets={rx.replacePackets}
              onStopReplay={stopReplay}
            />
          }
        />
      </div>
      <ConfigSidebar open={showConfig} onClose={() => { setShowConfig(false); fetch('/api/config').then(r => r.json()).then(setConfig) }} />
      <LogViewer open={showLogs} onClose={() => setShowLogs(false)} onStartReplay={startReplay} />
      <HelpModal open={showHelp} onClose={() => setShowHelp(false)} />
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
          newSession: () => {
            const tag = prompt('Session tag (optional):') ?? ''
            fetch('/api/logs/new', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ tag }),
            }).then(r => r.json()).then(d => {
              if (d.ok) showToast('New log session started', 'success')
            }).catch(() => showToast('Failed to start new session', 'error'))
          },
          tagSession: () => {
            const tag = prompt('Tag name:')
            if (!tag) return
            fetch('/api/logs/tag', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ tag }),
            }).then(r => r.json()).then(d => {
              if (d.ok) showToast(`Session tagged: ${tag}`, 'success')
            }).catch(() => showToast('Failed to tag session', 'error'))
          },
        }}
      />
      <KeyboardHintBar />
      <Toaster position="top-center" />
    </div>
  )
}
