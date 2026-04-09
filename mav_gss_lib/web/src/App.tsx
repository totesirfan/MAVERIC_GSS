import { useState, useEffect, useCallback, Suspense } from 'react'
import { useShortcuts } from '@/hooks/useShortcuts'
import { AppProvider, useAppConfig, useAppRx, useAppSession } from '@/hooks/useAppContext'
import { colors } from '@/lib/colors'
import { GlobalHeader, RenameSessionDialog } from '@/components/layout/GlobalHeader'
import { useTxSocket } from '@/hooks/useTxSocket'
import { useRxSocket } from '@/hooks/useRxSocket'
import { usePopOutBootstrap } from '@/hooks/usePopOutBootstrap'
import { RxPanel } from '@/components/rx/RxPanel'
import { TxPanel } from '@/components/tx/TxPanel'
import { AlarmStrip } from '@/components/shared/AlarmStrip'
import { Toaster } from '@/components/ui/sonner'
import { Skeleton } from '@/components/ui/skeleton'
import { MainDashboard } from '@/components/MainDashboard'
import { getPluginPages, type PluginPageDef } from '@/plugins/registry'

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
    <AppProvider>
      <AppShell />
    </AppProvider>
  )
}

/** Main app shell — lives inside AppProvider */
function AppShell() {
  const { config, setConfig } = useAppConfig()
  const [panelMode, setPanelMode] = useState(() => getPanelMode())
  const [page, setPage] = useState<string | null>(() => panelMode ? null : getPageMode())
  const [plugins, setPlugins] = useState<PluginPageDef[]>([])

  // Load plugin pages once mission is known
  useEffect(() => {
    const missionId = config?.general?.mission
    if (!missionId) return
    getPluginPages(missionId).then(setPlugins)
  }, [config?.general?.mission])

  const navigateTo = useCallback((target: string | null) => {
    const url = new URL(window.location.href)
    if (target) {
      url.searchParams.set('page', target)
    } else {
      url.searchParams.delete('page')
    }
    window.history.pushState({}, '', url.toString())
    setPage(target)
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

  // Escape key returns to main dashboard from plugin pages
  useShortcuts(
    [{ key: 'Escape', action: () => navigateTo(null) }],
    !!page,
  )

  useEffect(() => {
    const missionName = config?.general?.mission_name ?? 'Mission'
    document.title = `${missionName} GSS`
  }, [config?.general?.mission_name])

  const version = config?.general?.version ?? '...'
  const missionName = config?.general?.mission_name ?? 'Mission'

  // Plugin page
  if (page) {
    const activePlugin = plugins.find(p => p.id === page)
    return (
      <div className="flex flex-col h-full" style={{ backgroundColor: colors.bgApp }}>
        <PluginPageShell
          missionName={missionName}
          version={version}
          page={page}
          plugins={plugins}
          onBackClick={() => navigateTo(null)}
          plugin={activePlugin}
          configLoaded={config !== null}
        />
        <Toaster position="top-center" />
      </div>
    )
  }

  // Normal dashboard — MainDashboard renders its own GlobalHeader
  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: colors.bgApp }}>
      <MainDashboard
        config={config}
        onConfigChange={setConfig}
        missionName={missionName}
        version={version}
        plugins={plugins}
        onPluginClick={(id) => navigateTo(id)}
      />
      <Toaster position="top-center" />
    </div>
  )
}

/** Plugin page shell — owns RX socket for AlarmStrip */
function PluginPageShell({ missionName, version, page, plugins, onBackClick, plugin, configLoaded }: {
  missionName: string
  version: string
  page: string
  plugins: PluginPageDef[]
  onBackClick: () => void
  plugin: PluginPageDef | undefined
  configLoaded: boolean
}) {
  const rx = useAppRx()
  const session = useAppSession()

  return (
    <>
      <GlobalHeader
        missionName={missionName}
        version={version}
        page={page}
        plugins={plugins}
        onBackClick={onBackClick}
        onLogsClick={() => {}}
        onConfigClick={() => {}}
        onHelpClick={() => {}}
        session={session}
      />
      <RenameSessionDialog session={session} />
      <AlarmStrip status={rx.status} packets={rx.packets} replayMode={false} sessionResetGen={rx.sessionResetGen} />
      {plugin ? (
        <Suspense fallback={
          <div className="flex-1 flex items-center justify-center">
            <Skeleton className="h-8 w-48" />
          </div>
        }>
          <plugin.component />
        </Suspense>
      ) : configLoaded ? (
        <div className="flex-1 flex items-center justify-center">
          <span className="text-sm" style={{ color: colors.dim }}>Plugin not found</span>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center">
          <Skeleton className="h-8 w-48" />
        </div>
      )}
    </>
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
        />
      </div>
    </div>
  )
}
