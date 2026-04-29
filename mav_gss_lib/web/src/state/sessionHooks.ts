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

/** Column defs from session context. `defs` is null while SessionProvider is still fetching. */
export function useColumnDefs(): { defs: ColumnDefs | null } {
  const ctx = useSessionContext()
  return { defs: ctx.columns }
}
