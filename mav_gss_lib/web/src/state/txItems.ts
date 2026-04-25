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
 * In-flight dedup: the backend appends to history (and broadcasts "sent")
 * at ZMQ transmission time, but doesn't pop the queue until after the
 * post-send dwell. During that dwell window, queue[0] (status='sending')
 * and history[-1] represent the same logical command. The unified
 * timeline hides the phantom history entry and renders the live queue[0]
 * row as the single source of truth.
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
  // Suppress the last history entry when it mirrors the sending queue[0].
  // Match on event_id (unique per send) — title-based match wrongly hid the
  // previous history row when consecutive duplicate commands were queued
  // (e.g. three `com_ping eps`), because queue[0] for the next iter and
  // history[-1] from the previous iter share a title.
  const front = queue[0]
  const tail = history[history.length - 1]
  const frontEventId =
    front && front.type === 'mission_cmd' ? front.event_id ?? '' : ''
  const tailEventId =
    tail && tail.type === 'mission_cmd' ? tail.event_id ?? '' : ''
  const hideTailHistory =
    sendProgress !== null &&
    !!frontEventId &&
    frontEventId === tailEventId
  const visibleHistory = hideTailHistory ? history.slice(0, -1) : history

  const out: TxDisplayItem[] = []
  for (const h of visibleHistory) {
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
