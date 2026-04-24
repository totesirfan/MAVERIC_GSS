import { useMemo, useRef, useState, useEffect, useCallback, type ReactNode } from 'react'
import { arrayMove } from '@dnd-kit/sortable'
import { useTxSocket } from '@/hooks/useTxSocket'
import { deriveTxItems } from './txItems'
import { TxContext } from './txContexts'
import type { PendingReorderOverride, TxDisplayItem } from '@/lib/types'

export function TxProvider({ children }: { children: ReactNode }) {
  const tx = useTxSocket()

  // Stable per-slot uids for pending rows. The backend queue exposes no
  // per-item identity, so we track by position with a monotonic counter.
  // - Shrink from front (send completes): drop the leading uid(s).
  // - Grow at end (queue, import, duplicate): assign fresh uid(s).
  // - Non-front delete is a pre-existing ambiguity; mapping is positional.
  const uidCounterRef = useRef(1)
  const uidsRef = useRef<string[]>([])

  const [override, setOverride] = useState<PendingReorderOverride | null>(null)
  const overrideTokenRef = useRef(0)

  // Clear override whenever the backend queue reference changes — that's
  // our "backend echoed" signal.
  useEffect(() => {
    setOverride(null)
  }, [tx.queue])

  const items: TxDisplayItem[] = useMemo(() => {
    const newLen = tx.queue.length
    const prev = uidsRef.current
    let next: string[]
    if (newLen === 0) {
      next = []
    } else if (newLen < prev.length) {
      next = prev.slice(prev.length - newLen)
    } else if (newLen > prev.length) {
      const added = Array.from({ length: newLen - prev.length }, () =>
        `q-${uidCounterRef.current++}`,
      )
      next = [...prev, ...added]
    } else {
      next = prev
    }
    uidsRef.current = next
    return deriveTxItems(
      tx.queue,
      tx.history,
      tx.sendProgress,
      (i) => next[i] ?? `q-${uidCounterRef.current++}`,
      override,
    )
  }, [tx.queue, tx.history, tx.sendProgress, override])

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
    setOverride({ order: nextOrder, token: overrideTokenRef.current })

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
