import { createContext, useContext, type ReactNode } from 'react'
import { useRxSocket } from '@/hooks/useRxSocket'

type RxContextValue = ReturnType<typeof useRxSocket>

const RxContext = createContext<RxContextValue | null>(null)

export function RxProvider({ children }: { children: ReactNode }) {
  const rx = useRxSocket()
  return <RxContext.Provider value={rx}>{children}</RxContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useRx(): RxContextValue {
  const ctx = useContext(RxContext)
  if (!ctx) throw new Error('useRx must be used within RxProvider')
  return ctx
}
