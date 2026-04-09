import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import { useSession, type SessionState } from '@/hooks/useSession'
import type { GssConfig } from '@/lib/types'

interface SessionContextValue extends SessionState {
  config: GssConfig | null
  setConfig: (c: GssConfig) => void
}

const SessionContext = createContext<SessionContextValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const session = useSession()
  const [config, setConfig] = useState<GssConfig | null>(null)

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data: GssConfig) => setConfig(data))
      .catch(() => {})
  }, [])

  return (
    <SessionContext.Provider value={{ ...session, config, setConfig }}>
      {children}
    </SessionContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSessionContext(): SessionContextValue {
  const ctx = useContext(SessionContext)
  if (!ctx) throw new Error('useSessionContext must be used within SessionProvider')
  return ctx
}

// eslint-disable-next-line react-refresh/only-export-components
export function useConfig() {
  const ctx = useSessionContext()
  return { config: ctx.config, setConfig: ctx.setConfig }
}
