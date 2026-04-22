import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
  type PropsWithChildren,
} from 'react'
import { usePluginRxCustomSubscription } from '@/hooks/usePluginServices'
import type { TelemetryDomainState, TelemetryMsg } from './telemetry'

type TelemetryState = Record<string, TelemetryDomainState>
type CatalogMap = Record<string, unknown>

interface TelemetryApi {
  state: TelemetryState
  catalogs: CatalogMap
  ensureCatalog: (domain: string) => void
}

const TelemetryContext = createContext<TelemetryApi | null>(null)

/**
 * Platform-level provider. Knows nothing about mission domain names;
 * per-domain slices materialize on first message arrival. Missions
 * consume their own domain via useTelemetry('<their domain>').
 *
 * Catalog fetches are shared across all consumers: repeated calls for
 * the same domain return the cached value; concurrent first calls
 * share one in-flight promise; 404s are remembered so we don't
 * re-hammer the endpoint for domains without a catalog.
 */
export function TelemetryProvider({ children }: PropsWithChildren) {
  const subscribe = usePluginRxCustomSubscription()
  const [state, setState] = useState<TelemetryState>({})
  const [catalogs, setCatalogs] = useState<CatalogMap>({})
  const inFlight = useRef<Record<string, Promise<unknown> | 'missing'>>({})

  useEffect(() => {
    return subscribe((raw) => {
      if (raw?.type !== 'telemetry') return
      const msg = raw as unknown as TelemetryMsg
      if (msg.cleared) {
        setState((s) => ({ ...s, [msg.domain]: {} }))
        return
      }
      const changes = msg.changes
      if (!changes) return
      setState((s) => {
        const cur = s[msg.domain] ?? {}
        const next = msg.replay ? {} : { ...cur }
        for (const [k, entry] of Object.entries(changes)) {
          const existing = cur[k]
          if (!existing || entry.t >= existing.t) next[k] = entry
        }
        return { ...s, [msg.domain]: next }
      })
    })
  }, [subscribe])

  const ensureCatalog = useCallback((domain: string) => {
    if (domain in catalogs) return              // already resolved
    if (inFlight.current[domain]) return        // already fetching or missing
    const p = fetch(`/api/telemetry/${domain}/catalog`)
      .then((r) => {
        if (r.status === 404) {
          inFlight.current[domain] = 'missing'
          return null
        }
        if (!r.ok) throw new Error(`catalog fetch failed: ${r.status}`)
        return r.json()
      })
      .then((body) => {
        if (body !== null) {
          setCatalogs((c) => ({ ...c, [domain]: body }))
          delete inFlight.current[domain]
        }
      })
      .catch(() => { delete inFlight.current[domain] })
    inFlight.current[domain] = p
  }, [catalogs])

  return (
    <TelemetryContext.Provider value={{ state, catalogs, ensureCatalog }}>
      {children}
    </TelemetryContext.Provider>
  )
}

export function useTelemetry(domain: string): TelemetryDomainState {
  const ctx = useContext(TelemetryContext)
  if (!ctx) throw new Error('useTelemetry outside TelemetryProvider')
  return ctx.state[domain] ?? {}
}

/** Mission opt-in hook: returns the domain's catalog from the shared
 *  provider cache. First consumer triggers the fetch; concurrent
 *  consumers share the in-flight promise; resolved catalogs are
 *  reused across the whole app. Returns null while unknown or for
 *  domains without a catalog (after a 404). */
export function useTelemetryCatalog<T = unknown>(domain: string): T | null {
  const ctx = useContext(TelemetryContext)
  if (!ctx) throw new Error('useTelemetryCatalog outside TelemetryProvider')
  useEffect(() => { ctx.ensureCatalog(domain) }, [ctx, domain])
  return (ctx.catalogs[domain] as T | undefined) ?? null
}
