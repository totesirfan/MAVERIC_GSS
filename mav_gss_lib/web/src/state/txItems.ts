import type {
  TxQueueItem, TxHistoryItem, SendProgress, TxDisplayItem,
  PendingReorderOverride,
} from '@/lib/types'

/**
 * Merge backend queue + history into a single ordered render list.
 *
 * Layout: sent rows first (in send order), then pending rows. Pending
 * ordering can be overridden by `reorderOverride` to keep drag-and-drop
 * optimistic while the backend round-trips.
 *
 * Pure function of inputs — caller owns memoization.
 */
export function deriveTxItems(
  queue: TxQueueItem[],
  history: TxHistoryItem[],
  sendProgress: SendProgress | null,
  pendingUid: (queueIndex: number) => string,
  reorderOverride: PendingReorderOverride | null,
): TxDisplayItem[] {
  const out: TxDisplayItem[] = []
  for (const h of history) {
    out.push({
      uid: `h-${h.n}`,
      status: 'complete',
      source: 'history',
      historyN: h.n,
      item: h,
    })
  }

  // Pending indices: either natural or permuted by the local override.
  const pendingOrder: number[] =
    reorderOverride && reorderOverride.order.length === queue.length
      ? reorderOverride.order
      : queue.map((_, i) => i)

  for (let i = 0; i < pendingOrder.length; i++) {
    const qi = pendingOrder[i]
    const q = queue[qi]
    // The "sending" marker always belongs to whichever item is currently
    // being transmitted. Backend always pops from the front, so that is
    // always the first logical pending row — BEFORE any local reorder.
    const isSending = sendProgress !== null && qi === 0
    out.push({
      uid: pendingUid(qi),
      status: isSending ? 'sending' : 'pending',
      source: 'queue',
      queueIndex: qi,
      item: q,
    })
  }
  return out
}
