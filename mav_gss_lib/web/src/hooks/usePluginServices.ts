import { useCallback, useMemo } from 'react'
import { useRx, useRxStatus } from '@/state/rxHooks'
import { useTx } from '@/state/txHooks'
import { useSessionContext, useConfig } from '@/state/sessionHooks'
import type { RxPacket, RxStatus, GssConfig, SendProgress, GuardConfirm, TxQueueItem } from '@/lib/types'

export type CommandSchema = Record<string, Record<string, unknown>>

export interface PluginServices {
  packets: RxPacket[]
  status: RxStatus
  filterPackets: (predicate: (p: RxPacket) => boolean) => RxPacket[]
  queueCommand: (payload: Record<string, unknown>) => void
  sendAll: () => void
  abortSend: () => void
  sendProgress: SendProgress | null
  guardConfirm: GuardConfirm | null
  approveGuard: () => void
  rejectGuard: () => void
  txConnected: boolean
  config: GssConfig | null
  fetchSchema: () => Promise<CommandSchema>
  subscribeRxCustom: (fn: (msg: Record<string, unknown>) => void) => () => void
  sessionTag: string
  sessionGeneration: number
  /** Live pending TX queue (shared with main TxPanel). Filter by cmd_id in consumers. */
  pendingQueue: TxQueueItem[]
  /** Remove an item from the queue by its index in the full unfiltered queue. */
  removeQueueItem: (index: number) => void
}

export function usePluginServices(): PluginServices {
  const rx = useRx()
  const tx = useTx()
  const session = useSessionContext()
  const { config } = useConfig()

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
    sendAll: tx.sendAll,
    abortSend: tx.abortSend,
    sendProgress: tx.sendProgress,
    guardConfirm: tx.guardConfirm,
    approveGuard: tx.approveGuard,
    rejectGuard: tx.rejectGuard,
    txConnected: tx.connected,
    config,
    fetchSchema,
    subscribeRxCustom: rx.subscribeCustom,
    sessionTag: session.sessionTag,
    sessionGeneration: rx.sessionGeneration,
    pendingQueue: tx.queue,
    removeQueueItem: tx.deleteItem,
  }), [rx, tx, session, config, filterPackets, fetchSchema])
}

/**
 * Lightweight plugin-facing subscription hook for custom RX broadcasts.
 * Use this when a plugin only needs mission/plugin-specific WS messages and
 * should not rerender on the live packet stream.
 */
export function usePluginRxCustomSubscription(): PluginServices['subscribeRxCustom'] {
  const { subscribeCustom } = useRxStatus()
  return subscribeCustom
}
