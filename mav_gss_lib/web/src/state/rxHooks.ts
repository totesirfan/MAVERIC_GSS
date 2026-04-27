import { useContext } from 'react'
import type { RxPacket } from '@/lib/types'
import {
  RxDisplayTogglesContext,
  RxStatusContext,
  RxPacketsContext,
  RxStatsContext,
  type RxDisplayToggles,
  type RxSocketValue,
  type RxStatsValue,
  type RxStatusValue,
} from './rxContexts'

export function useRxStatus(): RxStatusValue {
  const ctx = useContext(RxStatusContext)
  if (!ctx) throw new Error('useRxStatus must be used within RxProvider')
  return ctx
}

export function useRxPackets(): RxPacket[] {
  const ctx = useContext(RxPacketsContext)
  if (ctx === null) throw new Error('useRxPackets must be used within RxProvider')
  return ctx
}

export function useRxStats(): RxStatsValue {
  const ctx = useContext(RxStatsContext)
  if (!ctx) throw new Error('useRxStats must be used within RxProvider')
  return ctx
}

export function useRxDisplayToggles(): RxDisplayToggles {
  const ctx = useContext(RxDisplayTogglesContext)
  if (!ctx) throw new Error('useRxDisplayToggles must be used within RxProvider')
  return ctx
}

/**
 * Legacy combined hook — subscribes to status, packets, AND stats, so the
 * consumer rerenders on every packet flush. Prefer the narrower hooks where
 * possible. Retained for `usePluginServices`, which exposes the full shape
 * to plugin pages.
 */
export function useRx(): RxSocketValue {
  const status = useRxStatus()
  const packets = useRxPackets()
  const stats = useRxStats()
  return { ...status, packets, stats }
}
