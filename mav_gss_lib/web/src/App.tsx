import { useState, useEffect, useCallback, useMemo, lazy, Suspense } from 'react'
import { useShortcuts, type Shortcut } from '@/hooks/useShortcuts'
import { SessionProvider, useSessionContext, useConfig } from '@/hooks/SessionProvider'
import { TxProvider, useTx } from '@/hooks/TxProvider'
import { RxProvider, useRxStatus, useRxDisplayToggles } from '@/hooks/RxProvider'
import { colors } from '@/lib/colors'
import { GlobalHeader, RenameSessionDialog } from '@/components/layout/GlobalHeader'
import { useTxSocket } from '@/hooks/useTxSocket'
import { useRxSocket } from '@/hooks/useRxSocket'
import { usePopOutBootstrap } from '@/hooks/usePopOutBootstrap'
import { RxPanel } from '@/components/rx/RxPanel'
import { TxPanel } from '@/components/tx/TxPanel'
import { Toaster } from '@/components/ui/sonner'
import {
  MainDashboard,
  RxCrcToastSentinel,
  AlarmStripWithPackets,
  ConfigSidebarSkeleton,
  LogViewerSkeleton,
  HelpModalSkeleton,
  CommandPaletteSkeleton,
} from '@/components/MainDashboard'
import { getPluginPages, type PluginPageDef } from '@/plugins/registry'
import { usePreflight } from '@/hooks/usePreflight'
import { PreflightScreen } from '@/components/shared/PreflightScreen'
import { TabViewport } from '@/components/layout/TabViewport'
import { buildNavigationTabs } from '@/components/layout/navigation'
import { KeyboardHintBar } from '@/components/layout/KeyboardHintBar'
import { isInputFocused } from '@/lib/utils'
import type { CommandPaletteActions } from '@/components/shared/CommandPalette'

const ConfigSidebar = lazy(() => import('@/components/config/ConfigSidebar').then((m) => ({ default: m.ConfigSidebar })))
const LogViewer = lazy(() => import('@/components/logs/LogViewer').then((m) => ({ default: m.LogViewer })))
const HelpModal = lazy(() => import('@/components/shared/HelpModal').then((m) => ({ default: m.HelpModal })))
const CommandPalette = lazy(() => import('@/components/shared/CommandPalette').then((m) => ({ default: m.CommandPalette })))

/** Check if app is running in a pop-out panel mode */
function getPanelMode(): 'tx' | 'rx' | null {
  const params = new URLSearchParams(window.location.search)
  const panel = params.get('panel')
  if (panel === 'tx') return 'tx'
  if (panel === 'rx') return 'rx'
  return null
}

/** Read the ?page= param for plugin page routing */
function getPageMode(): string | null {
  const params = new URLSearchParams(window.location.search)
  return params.get('page') || null
}

export default function App() {
  const panelMode = getPanelMode()

  // Pop-out windows stay outside the provider — they manage their own state
  if (panelMode === 'tx') {
    return <PopOutTx />
  }
  if (panelMode === 'rx') {
    return <PopOutRx />
  }

  return (
    <SessionProvider>
      <TxProvider>
        <RxProvider>
          <AppShell />
          <PreflightOverlay />
        </RxProvider>
      </TxProvider>
    </SessionProvider>
  )
}

/** Main app shell — lives inside Session/Tx/Rx providers */
function AppShell() {
  const { config, setConfig } = useConfig()
  const [panelMode, setPanelMode] = useState(() => getPanelMode())
  const [page, setPage] = useState<string | null>(() => panelMode ? null : getPageMode())
  const [plugins, setPlugins] = useState<PluginPageDef[]>([])

  // Shell modal state (lifted from old MainDashboard)
  const [showLogs, setShowLogs] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const [showCommand, setShowCommand] = useState(false)
  const [replaySession, setReplaySession] = useState<string | null>(null)
  const [confirmSendSignal, setConfirmSendSignal] = useState(0)
  const [confirmClearSignal, setConfirmClearSignal] = useState(0)

  const rx = useRxStatus()
  const tx = useTx()
  const session = useSessionContext()
  const rxToggles = useRxDisplayToggles()

  // Load plugin pages once mission is known
  useEffect(() => {
    const missionId = config?.general?.mission
    if (!missionId) return
    getPluginPages(missionId).then(setPlugins)
  }, [config?.general?.mission])

  const navigateTo = useCallback((target: string | null) => {
    const url = new URL(window.location.href)
    if (target && target !== '__dashboard__') {
      url.searchParams.set('page', target)
    } else {
      url.searchParams.delete('page')
    }
    window.history.pushState({}, '', url.toString())
    setPage(target === '__dashboard__' ? null : target)
  }, [])

  // Browser back/forward
  useEffect(() => {
    const onPopState = () => {
      setPanelMode(getPanelMode())
      setPage(getPageMode())
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    const missionName = config?.general?.mission_name ?? 'Mission'
    document.title = `${missionName} GSS`
  }, [config?.general?.mission_name])

  const version = config?.general?.version ?? '...'
  const missionName = config?.general?.mission_name ?? 'Mission'

  // Derived state
  const activeTabId = page ?? '__dashboard__'
  const navigationTabs = useMemo(() => buildNavigationTabs(plugins), [plugins])

  // Replay callbacks
  const startReplay = useCallback((sessionId: string) => {
    rx.enterReplay()
    setReplaySession(sessionId)
  }, [rx])

  const stopReplay = useCallback(() => {
    rx.exitReplay()
    setReplaySession(null)
  }, [rx])

  // Build palette actions — dashboard-scoped entries are conditional
  const paletteActions = useMemo<CommandPaletteActions>(() => {
    const base: CommandPaletteActions = {
      toggleHex: rxToggles.toggleHex,
      toggleFrame: rxToggles.toggleFrame,
      toggleWrapper: rxToggles.toggleWrapper,
      toggleUplink: rxToggles.toggleUplink,
      openConfig: () => setShowConfig(true),
      openLogs: () => setShowLogs(true),
      openHelp: () => setShowHelp(true),
      newSession: () => session.setOpenNewSession(true),
      tagSession: () => session.setOpenRename(true),
    }
    if (activeTabId === '__dashboard__') {
      return {
        ...base,
        confirmSend: () => setConfirmSendSignal(n => n + 1),
        confirmClear: () => setConfirmClearSignal(n => n + 1),
        undoLast: tx.undoLast,
        abortSend: tx.abortSend,
      }
    }
    return base
  }, [activeTabId, rxToggles, tx, session])

  // Shell-global shortcuts
  const shellShortcuts = useMemo<Shortcut[]>(() => [
    { key: 'k', ctrl: true, action: () => setShowCommand(v => !v) },
    { key: '?', action: () => setShowHelp(v => !v), when: () => !isInputFocused() },
    { key: 'Escape', action: () => setShowConfig(false), when: () => showConfig },
    { key: 'Escape', action: () => setShowLogs(false), when: () => showLogs },
    { key: 'Escape', action: () => setShowHelp(false), when: () => showHelp },
  ], [showConfig, showLogs, showHelp])

  useShortcuts(shellShortcuts)

  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: colors.bgApp }}>
      <GlobalHeader
        missionName={missionName}
        version={version}
        tabs={navigationTabs}
        activeTabId={activeTabId}
        onTabClick={(id) => navigateTo(id === '__dashboard__' ? null : id)}
        onLogsClick={() => setShowLogs(v => !v)}
        onConfigClick={() => setShowConfig(v => !v)}
        onHelpClick={() => setShowHelp(v => !v)}
        session={session}
      />
      <RenameSessionDialog session={session} />
      <RxCrcToastSentinel />
      <AlarmStripWithPackets status={rx.status} replayMode={rx.replayMode} sessionResetGen={rx.sessionResetGen} />
      <TabViewport
        plugins={plugins}
        activeId={activeTabId}
        renderDashboard={() => (
          <MainDashboard
            config={config}
            confirmSendSignal={confirmSendSignal}
            confirmClearSignal={confirmClearSignal}
            replaySession={replaySession}
            onStopReplay={stopReplay}
          />
        )}
      />
      {/* Lazy modals */}
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
            navigationTabs={navigationTabs}
            onNavigate={(id) => { navigateTo(id === '__dashboard__' ? null : id) }}
            actions={paletteActions}
          />
        </Suspense>
      )}
      <KeyboardHintBar activeTabId={activeTabId} anyShellModalOpen={showLogs || showConfig || showHelp} />
      <Toaster position="top-center" />
    </div>
  )
}

/** Frosted overlay that blurs the dashboard during preflight, then lifts to reveal it */
function PreflightOverlay() {
  const preflight = usePreflight()
  const { config } = useConfig()
  const version = config?.general?.version
  const buildSha = typeof __BUILD_SHA__ === 'string' ? __BUILD_SHA__ : undefined
  const [dismissing, setDismissing] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  // No auto-dismiss — the overlay stays visible until the user presses LAUNCH.
  // After LAUNCH triggers dismissing=true, unmount after the unblur animation (800ms).
  useEffect(() => {
    if (dismissing) {
      const t = setTimeout(() => setDismissed(true), 850)
      return () => clearTimeout(t)
    }
  }, [dismissing])

  if (dismissed) return null

  return (
    <PreflightScreen
      checks={preflight.checks}
      summary={preflight.summary}
      connected={preflight.connected}
      dismissing={dismissing}
      onContinue={() => {
        preflight.signalLaunched()
        setDismissing(true)
      }}
      onRerun={preflight.rerun}
      updateState={preflight.updateState}
      updatePhases={preflight.updatePhases}
      onShowConfirm={preflight.showConfirm}
      onCancelConfirm={preflight.cancelConfirm}
      onApplyUpdate={preflight.applyUpdate}
      onReloadPage={preflight.reloadPage}
      version={version}
      buildSha={buildSha}
    />
  )
}

/** Pop-out TX panel — standalone window */
function PopOutTx() {
  const { config } = usePopOutBootstrap()
  const tx = useTxSocket()
  const uplinkMode = config?.tx?.uplink_mode ?? ''

  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: colors.bgApp }}>
      <div className="flex-1 p-2">
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
        triggerConfirmSend={0}
        triggerConfirmClear={0}
      />
      </div>
    </div>
  )
}

/** Pop-out RX panel — standalone window */
function PopOutRx() {
  const { config } = usePopOutBootstrap()
  const rx = useRxSocket()

  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: colors.bgApp }}>
      <div className="flex-1 p-2">
        <RxPanel
          config={config}
          packets={rx.packets} status={rx.status}
          packetStats={rx.stats}
          columns={rx.columns}
          replayMode={rx.replayMode}
          replaySession={null}
          replacePackets={rx.replacePackets}
          onStopReplay={() => {}}
          sessionResetGen={rx.sessionResetGen}
          sessionTag={rx.sessionResetTag || ''}
          blackoutUntil={rx.blackoutUntil}
        />
      </div>
    </div>
  )
}
