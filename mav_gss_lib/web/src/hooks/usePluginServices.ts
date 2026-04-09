import { useCallback, useMemo } from 'react'
import { useAppRx, useAppTx, useAppSession, useAppConfig } from '@/hooks/useAppContext'
import type { RxPacket, RxStatus, GssConfig } from '@/lib/types'

export type CommandSchema = Record<string, Record<string, unknown>>

export interface PluginServices {
  packets: RxPacket[]
  status: RxStatus
  filterPackets: (predicate: (p: RxPacket) => boolean) => RxPacket[]
  queueCommand: (payload: Record<string, unknown>) => void
  txConnected: boolean
  config: GssConfig | null
  fetchSchema: () => Promise<CommandSchema>
  subscribeRxCustom: (fn: (msg: Record<string, unknown>) => void) => () => void
  sessionTag: string
  sessionResetGen: number
}

export function usePluginServices(): PluginServices {
  const rx = useAppRx()
  const tx = useAppTx()
  const session = useAppSession()
  const { config } = useAppConfig()

  const filterPackets = useCallback(
    (predicate: (p: RxPacket) => boolean) => rx.packets.filter(predicate),
    [rx.packets],
  )

  const fetchSchema = useCallback(
    () => fetch('/api/schema').then(r => r.json()) as Promise<CommandSchema>,
    [],
  )

  return useMemo(() => ({
    packets: rx.packets,
    status: rx.status,
    filterPackets,
    queueCommand: tx.queueMissionCmd,
    txConnected: tx.connected,
    config,
    fetchSchema,
    subscribeRxCustom: rx.subscribeCustom,
    sessionTag: session.tag,
    sessionResetGen: rx.sessionResetGen,
  }), [rx, tx, session, config, filterPackets, fetchSchema])
}
