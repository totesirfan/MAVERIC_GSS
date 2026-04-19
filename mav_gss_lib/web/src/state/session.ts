import { useContext } from 'react'
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
