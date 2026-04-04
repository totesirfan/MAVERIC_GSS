import { useState, useEffect } from 'react'
import { GlobalHeader } from '@/components/layout/GlobalHeader'
import { SplitPane } from '@/components/layout/SplitPane'
import { useRxSocket } from '@/hooks/useRxSocket'
import { useTxSocket } from '@/hooks/useTxSocket'
import { RxPanel } from '@/components/rx/RxPanel'
import { TxPanel } from '@/components/tx/TxPanel'
import { ConfigSidebar } from '@/components/config/ConfigSidebar'
import { LogViewer } from '@/components/logs/LogViewer'
import { HelpModal } from '@/components/shared/HelpModal'
import type { GssConfig } from '@/lib/types'

export default function App() {
  const rx = useRxSocket()
  const tx = useTxSocket()

  const [config, setConfig] = useState<GssConfig | null>(null)
  const [showLogs, setShowLogs] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [showHelp, setShowHelp] = useState(false)

  // all modal states now wired up

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data: GssConfig) => setConfig(data))
      .catch(() => {/* offline */})
  }, [])

  const version = config?.general?.version ?? '...'
  const frequency = config?.tx?.frequency ?? 0
  const uplinkMode = config?.tx?.uplink_mode ?? ''

  return (
    <div className="flex flex-col h-full">
      <GlobalHeader
        version={version}
        zmqRx={rx.status.zmq}
        zmqTx={tx.connected ? 'LIVE' : 'DOWN'}
        frequency={frequency}
        uplinkMode={uplinkMode}
        onLogsClick={() => setShowLogs((v) => !v)}
        onConfigClick={() => setShowConfig((v) => !v)}
        onHelpClick={() => setShowHelp((v) => !v)}
      />
      <SplitPane
        left={
          <TxPanel
            queue={tx.queue}
            summary={tx.summary}
            history={tx.history}
            sendProgress={tx.sendProgress}
            guardConfirm={tx.guardConfirm}
            error={tx.error}
            uplinkMode={uplinkMode}
            queueCommand={tx.queueCommand}
            queueBuilt={tx.queueBuilt}
            deleteItem={tx.deleteItem}
            clearQueue={tx.clearQueue}
            undoLast={tx.undoLast}
            toggleGuard={tx.toggleGuard}
            reorder={tx.reorder}
            addDelay={tx.addDelay}
            editDelay={tx.editDelay}
            sendAll={tx.sendAll}
            abortSend={tx.abortSend}
            approveGuard={tx.approveGuard}
            rejectGuard={tx.rejectGuard}
          />
        }
        right={
          <RxPanel packets={rx.packets} status={rx.status} />
        }
      />
      <ConfigSidebar open={showConfig} onClose={() => { setShowConfig(false); fetch('/api/config').then(r => r.json()).then(setConfig) }} />
      <LogViewer open={showLogs} onClose={() => setShowLogs(false)} />
      <HelpModal open={showHelp} onClose={() => setShowHelp(false)} />
    </div>
  )
}
