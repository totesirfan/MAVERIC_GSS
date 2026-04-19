import { useState, useEffect, type ReactNode } from 'react'
import { useSession } from '@/hooks/useSession'
import type { GssConfig } from '@/lib/types'
import { SessionContext } from './sessionContexts'

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
