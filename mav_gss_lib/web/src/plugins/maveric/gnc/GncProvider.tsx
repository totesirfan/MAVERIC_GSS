/**
 * GncProvider — root-mounted state for the GNC dashboard.
 *
 * Mission-owned (MAVERIC), mounted at the app root by the platform's
 * MissionProviders wrapper. Built on top of `useTelemetry('gnc')` and
 * `useTelemetryCatalog<CatalogEntry[]>('gnc')` — no direct WS
 * subscription, no direct REST fetch.
 *
 * Why root-level and not inside GNCPage:
 *   • The platform TelemetryProvider receives the replay-on-connect
 *     snapshot at app start. A page-local provider would miss the
 *     replay and open blank until the next live RES.
 *   • `lastUpdateAt` accumulates across navigation.
 *
 * The provider projects the platform's `{ v, t }` entries into the
 * GNC-local `{ value, t }` shape (`RegisterSnapshot`), so all the
 * existing dashboard/register consumers keep reading `snap.value` and
 * `snap.t` with no per-consumer mapping.
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type PropsWithChildren,
} from 'react'
import { useTelemetry, useTelemetryCatalog } from '@/state/TelemetryProvider'
import type { CatalogEntry, GncState, RegisterSnapshot, RegisterValue } from './types'

interface GncApi {
  state: GncState
  catalog: CatalogEntry[]
  lastUpdateAt: number | null
  clearSnapshot: () => Promise<void>
}

const GncContext = createContext<GncApi | null>(null)

export function GncProvider({ children }: PropsWithChildren) {
  const raw = useTelemetry('gnc')
  const catalog = useTelemetryCatalog<CatalogEntry[]>('gnc')

  // Project TelemetryEntry `{ v, t, ... }` into RegisterSnapshot
  // `{ value, t }` so every consumer under gnc/** reads the same
  // shape the pre-v2 code already reads, minus dropped debug fields.
  const state = useMemo<GncState>(() => {
    const out: GncState = {}
    for (const [key, entry] of Object.entries(raw)) {
      out[key] = {
        value: entry.v as RegisterValue,
        t: entry.t,
      } satisfies RegisterSnapshot
    }
    return out
  }, [raw])

  const lastUpdateAt = useMemo<number | null>(() => {
    let newest = 0
    for (const snap of Object.values(state)) {
      if (snap.t > newest) newest = snap.t
    }
    return newest > 0 ? newest : null
  }, [state])

  const clearSnapshot = useCallback(async () => {
    // Fire-and-forget DELETE against the platform route; server broadcasts
    // `{type:"telemetry", domain:"gnc", cleared:true}` which the
    // TelemetryProvider turns into an empty domain state, which bubbles
    // through our useMemo above and empties `state`.
    await fetch('/api/telemetry/gnc/snapshot', { method: 'DELETE' }).catch(() => {})
  }, [])

  const api = useMemo<GncApi>(
    () => ({ state, catalog: catalog ?? [], lastUpdateAt, clearSnapshot }),
    [state, catalog, lastUpdateAt, clearSnapshot],
  )

  return <GncContext.Provider value={api}>{children}</GncContext.Provider>
}

export function useGnc(): GncApi {
  const ctx = useContext(GncContext)
  if (!ctx) {
    throw new Error(
      'useGnc must be used inside <GncProvider>. '
      + 'Check that plugins/maveric/providers.ts registers GncProvider.',
    )
  }
  return ctx
}
