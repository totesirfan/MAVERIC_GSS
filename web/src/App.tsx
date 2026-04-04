import { useState, useEffect } from 'react'
import { GlobalHeader } from '@/components/layout/GlobalHeader'
import { SplitPane } from '@/components/layout/SplitPane'
import { useRxSocket } from '@/hooks/useRxSocket'
import { useTxSocket } from '@/hooks/useTxSocket'
import { colors } from '@/lib/colors'
import type { GssConfig } from '@/lib/types'

export default function App() {
  const rx = useRxSocket()
  const tx = useTxSocket()

  const [config, setConfig] = useState<GssConfig | null>(null)
  const [showLogs, setShowLogs] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [showHelp, setShowHelp] = useState(false)

  // suppress unused warnings until later tasks wire these up
  void showLogs; void showConfig; void showHelp

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
          <div className="flex-1 flex items-center justify-center" style={{ color: colors.dim }}>
            TX Panel
          </div>
        }
        right={
          <div className="flex-1 flex items-center justify-center" style={{ color: colors.dim }}>
            RX Panel — {rx.packets.length} packets
          </div>
        }
      />
    </div>
  )
}
