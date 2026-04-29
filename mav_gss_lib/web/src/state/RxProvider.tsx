import { useMemo, useState, type ReactNode } from 'react'
import { useRxSocket } from '@/hooks/useRxSocket'
import {
  RxDisplayTogglesContext,
  RxStatusContext,
  RxPacketsContext,
  RxStatsContext,
  type RxDisplayToggles,
  type RxStatusValue,
} from './rxContexts'

export function RxProvider({ children }: { children: ReactNode }) {
  const rx = useRxSocket()
  const { packets, stats, ...rest } = rx

  // `packets` and `stats` change on every 50ms flush. Everything else only
  // changes on rare events (status message,
  // session reset). We memoize `rest` against its slow-changing fields so
  // status subscribers don't rerender 20×/sec under RX traffic.
  const statusValue = useMemo<RxStatusValue>(
    () => rest,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      rest.status,
      rest.connected,
      rest.sessionGeneration,
      rest.sessionTag,
      rest.clearPackets,
      rest.subscribeCustom,
      rest.blackoutUntil,
    ],
  )

  const [showHex, setShowHex] = useState(false)
  const [showFrame, setShowFrame] = useState(false)
  const [showWrapper, setShowWrapper] = useState(false)
  const [hideUplink, setHideUplink] = useState(true)

  const displayToggles = useMemo<RxDisplayToggles>(() => ({
    showHex,
    showFrame,
    showWrapper,
    hideUplink,
    toggleHex: () => setShowHex(v => !v),
    toggleFrame: () => setShowFrame(v => !v),
    toggleWrapper: () => setShowWrapper(v => !v),
    toggleUplink: () => setHideUplink(v => !v),
  }), [showHex, showFrame, showWrapper, hideUplink])

  return (
    <RxDisplayTogglesContext.Provider value={displayToggles}>
      <RxStatusContext.Provider value={statusValue}>
        <RxStatsContext.Provider value={stats}>
          <RxPacketsContext.Provider value={packets}>
            {children}
          </RxPacketsContext.Provider>
        </RxStatsContext.Provider>
      </RxStatusContext.Provider>
    </RxDisplayTogglesContext.Provider>
  )
}
