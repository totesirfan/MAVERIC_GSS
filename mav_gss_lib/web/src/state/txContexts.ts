import { createContext } from 'react'
import type { useTxSocket } from '@/hooks/useTxSocket'
import type { TxDisplayItem } from '@/lib/types'

type Base = ReturnType<typeof useTxSocket>
export type TxContextValue = Base & {
  items: TxDisplayItem[]
  /**
   * Atomic drag reorder: resolves the two drag endpoints against the
   * currently-displayed `items` (override-aware), installs the optimistic
   * override, and dispatches `tx.reorder(fromPos, toPos)` where positions
   * are in the display order. Returns true if applied, false if rejected
   * (same uid, cross-segment drop, or unknown uid).
   */
  applyDragReorder: (activeUid: string, overUid: string) => boolean
}

export const TxContext = createContext<TxContextValue | null>(null)
