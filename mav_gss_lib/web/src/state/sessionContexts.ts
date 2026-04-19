import { createContext } from 'react'
import type { SessionState } from '@/hooks/useSession'
import type { GssConfig } from '@/lib/types'

export interface SessionContextValue extends SessionState {
  config: GssConfig | null
  setConfig: (c: GssConfig) => void
}

export const SessionContext = createContext<SessionContextValue | null>(null)
