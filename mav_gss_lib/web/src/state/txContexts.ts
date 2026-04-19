import { createContext } from 'react'
import type { useTxSocket } from '@/hooks/useTxSocket'

export type TxContextValue = ReturnType<typeof useTxSocket>

export const TxContext = createContext<TxContextValue | null>(null)
