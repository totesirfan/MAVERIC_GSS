import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import { useRxSocket } from '@/hooks/useRxSocket'
import { useTxSocket } from '@/hooks/useTxSocket'
import { useSession } from '@/hooks/useSession'
import type { GssConfig } from '@/lib/types'

interface AppContextValue {
  rx: ReturnType<typeof useRxSocket>
  tx: ReturnType<typeof useTxSocket>
  session: ReturnType<typeof useSession>
  config: GssConfig | null
  setConfig: (c: GssConfig) => void
}

const AppContext = createContext<AppContextValue | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const rx = useRxSocket()
  const tx = useTxSocket()
  const session = useSession()
  const [config, setConfig] = useState<GssConfig | null>(null)

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data: GssConfig) => setConfig(data))
      .catch(() => {})
  }, [])

  return (
    <AppContext.Provider value={{ rx, tx, session, config, setConfig }}>
      {children}
    </AppContext.Provider>
  )
}

function useAppContext() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useAppContext must be used within AppProvider')
  return ctx
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAppRx() { return useAppContext().rx }
// eslint-disable-next-line react-refresh/only-export-components
export function useAppTx() { return useAppContext().tx }
// eslint-disable-next-line react-refresh/only-export-components
export function useAppSession() { return useAppContext().session }
// eslint-disable-next-line react-refresh/only-export-components
export function useAppConfig() {
  const ctx = useAppContext()
  return { config: ctx.config, setConfig: ctx.setConfig }
}
