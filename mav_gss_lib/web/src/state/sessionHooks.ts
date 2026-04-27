import { useContext } from 'react'
import type { ColumnDefs } from '@/lib/types'
import { SessionContext, type SessionContextValue } from './sessionContexts'

export function useSessionContext(): SessionContextValue {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSessionContext must be used within SessionProvider')
  return ctx
}

export function useConfig() {
  const ctx = useSessionContext()
  return { config: ctx.config, setConfig: ctx.setConfig }
}

/**
 * Returns column defs from session context plus a `hasProvider` flag.
 *
 * - Main window: `hasProvider=true`, `defs` is null while SessionProvider is
 *   still fetching, then populated. Consumers should read `defs` and avoid
 *   doing their own fetch (SessionProvider owns it).
 * - Pop-out windows (opened via `?panel=tx|rx`, bootstrapped outside
 *   SessionProvider): `hasProvider=false`. Consumers should run their own
 *   fetch as a fallback.
 *
 * This tri-state signal (present-but-loading vs absent) prevents the
 * duplicate-fetch race where a main-window consumer's effect fires before
 * SessionProvider finishes.
 */
export function useColumnDefs(): { defs: ColumnDefs | null; hasProvider: boolean } {
  const ctx = useContext(SessionContext)
  return { defs: ctx?.columns ?? null, hasProvider: ctx !== null }
}
