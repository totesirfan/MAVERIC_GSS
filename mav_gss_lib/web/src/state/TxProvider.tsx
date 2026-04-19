import { type ReactNode } from 'react'
import { useTxSocket } from '@/hooks/useTxSocket'
import { TxContext } from './txContexts'

export function TxProvider({ children }: { children: ReactNode }) {
  const tx = useTxSocket()
  return <TxContext.Provider value={tx}>{children}</TxContext.Provider>
}
