import { createContext, useContext, type ReactNode } from 'react'
import { useTxSocket } from '@/hooks/useTxSocket'

type TxContextValue = ReturnType<typeof useTxSocket>

const TxContext = createContext<TxContextValue | null>(null)

export function TxProvider({ children }: { children: ReactNode }) {
  const tx = useTxSocket()
  return <TxContext.Provider value={tx}>{children}</TxContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTx(): TxContextValue {
  const ctx = useContext(TxContext)
  if (!ctx) throw new Error('useTx must be used within TxProvider')
  return ctx
}
