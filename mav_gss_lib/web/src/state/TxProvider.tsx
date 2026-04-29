import { useMemo, useRef, useState, useCallback, type ReactNode } from 'react'
import { arrayMove } from '@dnd-kit/sortable'
import { useTxSocket } from '@/hooks/useTxSocket'
import { deriveTxItems } from './txItems'
import { TxContext } from './txContexts'
import type { PendingReorderOverride, TxDisplayItem } from '@/lib/types'

type ActiveReorderOverride = PendingReorderOverride & {
  queueRef: readonly unknown[]
}

export function TxProvider({ children }: { children: ReactNode }) {
  const tx = useTxSocket()

  const [override, setOverride] = useState<ActiveReorderOverride | null>(null)
  const overrideTokenRef = useRef(0)
  const activeOverride = override?.queueRef === tx.queue ? override : null

  const items: TxDisplayItem[] = useMemo(() => {
    return deriveTxItems(
      tx.queue,
      tx.history,
      tx.sendProgress,
      (i) => `q-${i}`,
      activeOverride,
    )
  }, [tx.queue, tx.history, tx.sendProgress, activeOverride])

  const applyDragReorder = useCallback((activeUid: string, overUid: string): boolean => {
    if (activeUid === overUid) return false
    const pendingDisplayed = items.filter(i => i.source === 'queue')
    const activeItem = pendingDisplayed.find(i => i.uid === activeUid)
    const overItem = pendingDisplayed.find(i => i.uid === overUid)
    if (!activeItem || !overItem) return false
    const fromPos = pendingDisplayed.indexOf(activeItem)
    const toPos = pendingDisplayed.indexOf(overItem)
    if (fromPos < 0 || toPos < 0 || fromPos === toPos) return false

    // New override = the permutation of backend queue-indices in display
    // order after the user's drag is applied. Used by deriveTxItems for
    // the optimistic view; cleared when the backend echoes queue_update.
    const currentOrder = pendingDisplayed.map(i => i.queueIndex!)
    const nextOrder = arrayMove(currentOrder, fromPos, toPos)
    overrideTokenRef.current += 1
    setOverride({ order: nextOrder, token: overrideTokenRef.current, queueRef: tx.queue })

    // Dispatch to backend as (fromPos, toPos). useTxSocket.reorder only
    // uses queue length, not contents, so this is a position-relative
    // permutation that composes correctly if the backend has already
    // applied earlier in-flight orders.
    tx.reorder(fromPos, toPos)
    return true
  }, [items, tx])

  const value = useMemo(
    () => ({ ...tx, items, applyDragReorder }),
    [tx, items, applyDragReorder],
  )
  return <TxContext.Provider value={value}>{children}</TxContext.Provider>
}
