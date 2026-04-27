import { useContext } from 'react'
import { TxContext, type TxContextValue } from './txContexts'

export function useTx(): TxContextValue {
  const ctx = useContext(TxContext)
  if (!ctx) throw new Error('useTx must be used within TxProvider')
  return ctx
}
