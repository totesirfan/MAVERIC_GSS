import { useCallback, useEffect, useRef, useState } from 'react'
import { usePluginServices } from '@/hooks/usePluginServices'
import type { GncState, GncRegisterUpdateMsg, RegisterSnapshot } from './types'

/** Subscribe to `gnc_register_update` WS messages and seed state from
 *  the persistent backend store at `/api/plugins/gnc/snapshot`.
 *
 *  `received_at_ms` is server-anchored, so age stays correct even
 *  across MAV_WEB restarts, tab switches, and session resets. The
 *  snapshot represents last-known satellite state — it is deliberately
 *  **not** wiped on session reset (starting a new log is an operator
 *  bookkeeping action, not an ADCS state change). Use `clearSnapshot()`
 *  to explicitly discard.
 */
export function useGncRegisters(): {
  state: GncState
  lastUpdateAt: number | null
  clearSnapshot: () => Promise<void>
} {
  const { subscribeRxCustom, sessionResetGen } = usePluginServices()
  const [state, setState] = useState<GncState>({})
  const [lastUpdateAt, setLastUpdateAt] = useState<number | null>(null)

  const seedFromDisk = useCallback((signal?: AbortSignal) => {
    return fetch('/api/plugins/gnc/snapshot', { signal })
      .then((r) => (r.ok ? r.json() : {}))
      .then((data: Record<string, RegisterSnapshot>) => {
        if (!data || typeof data !== 'object') return
        let newest = 0
        for (const snap of Object.values(data)) {
          if (snap.received_at_ms > newest) newest = snap.received_at_ms
        }
        // Live updates that arrived before the seed resolved win, so
        // merge disk values UNDER current state.
        setState((prev) => ({ ...data, ...prev }))
        setLastUpdateAt((p) => (p && p > newest ? p : (newest || p)))
      })
      .catch(() => { /* offline backend — just wait for WS */ })
  }, [])

  // Seed on mount.
  useEffect(() => {
    const ac = new AbortController()
    void seedFromDisk(ac.signal)
    return () => ac.abort()
  }, [seedFromDisk])

  // Re-seed on session reset. We re-fetch (rather than wipe) because
  // the disk store is authoritative and may hold newer values than the
  // in-memory cache when the user reconnects after being away.
  const mountGen = useRef(sessionResetGen)
  useEffect(() => {
    if (sessionResetGen === mountGen.current) return
    mountGen.current = sessionResetGen
    void seedFromDisk()
  }, [sessionResetGen, seedFromDisk])

  // Live updates.
  useEffect(() => {
    return subscribeRxCustom((msg) => {
      if (msg.type !== 'gnc_register_update') return
      const update = msg as unknown as GncRegisterUpdateMsg
      if (!update.registers) return
      setState((prev) => ({ ...prev, ...update.registers }))
      let newest = 0
      for (const snap of Object.values(update.registers)) {
        if (snap.received_at_ms > newest) newest = snap.received_at_ms
      }
      if (newest > 0) setLastUpdateAt(newest)
    })
  }, [subscribeRxCustom])

  const clearSnapshot = useCallback(async () => {
    await fetch('/api/plugins/gnc/snapshot', { method: 'DELETE' }).catch(() => {})
    setState({})
    setLastUpdateAt(null)
  }, [])

  return { state, lastUpdateAt, clearSnapshot }
}
