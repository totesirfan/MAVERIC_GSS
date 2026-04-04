import { useEffect, useRef, useState, useCallback } from 'react'
import { createSocket } from '@/lib/ws'
import type {
  TxQueueItem, TxQueueSummary, TxHistoryItem,
  SendProgress, GuardConfirm,
} from '@/lib/types'

interface TxSocketMessage {
  type: string
  queue?: TxQueueItem[]
  summary?: TxQueueSummary
  history?: TxHistoryItem[]
  progress?: SendProgress
  confirm?: GuardConfirm
  error?: string
  [key: string]: unknown
}

export function useTxSocket() {
  const [queue, setQueue] = useState<TxQueueItem[]>([])
  const [summary, setSummary] = useState<TxQueueSummary>({ cmds: 0, guards: 0, est_time_s: 0 })
  const [history, setHistory] = useState<TxHistoryItem[]>([])
  const [sendProgress, setSendProgress] = useState<SendProgress | null>(null)
  const [guardConfirm, setGuardConfirm] = useState<GuardConfirm | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)
  const socketRef = useRef<ReturnType<typeof createSocket> | null>(null)

  useEffect(() => {
    const sock = createSocket(
      '/ws/tx',
      (data) => {
        const msg = data as TxSocketMessage
        switch (msg.type) {
          case 'queue':
            if (msg.queue) setQueue(msg.queue)
            if (msg.summary) setSummary(msg.summary)
            break
          case 'history':
            if (msg.history) setHistory(msg.history)
            break
          case 'send_progress':
            if (msg.progress) setSendProgress(msg.progress)
            break
          case 'send_complete':
            setSendProgress(null)
            break
          case 'send_aborted':
            setSendProgress(null)
            break
          case 'guard_confirm':
            if (msg.confirm) setGuardConfirm(msg.confirm)
            break
          case 'error':
            if (msg.error) setError(msg.error)
            setTimeout(() => setError(null), 5000)
            break
          case 'queued':
            // item was queued successfully, queue update follows
            break
        }
      },
      setConnected,
    )
    socketRef.current = sock
    return () => sock.close()
  }, [])

  const send = useCallback((action: string, payload?: Record<string, unknown>) => {
    socketRef.current?.send({ action, ...payload })
  }, [])

  const queueCommand = useCallback((line: string) => {
    send('queue_cmd', { line })
  }, [send])

  const queueBuilt = useCallback((cmd: string, args: Record<string, string>, dest?: string, echo?: string, ptype?: string) => {
    send('queue_built', { cmd, args, dest, echo, ptype })
  }, [send])

  const deleteItem = useCallback((index: number) => {
    send('delete', { index })
  }, [send])

  const clearQueue = useCallback(() => {
    send('clear')
  }, [send])

  const undoLast = useCallback(() => {
    send('undo')
  }, [send])

  const toggleGuard = useCallback((index: number) => {
    send('toggle_guard', { index })
  }, [send])

  const reorder = useCallback((oldIndex: number, newIndex: number) => {
    send('reorder', { old_index: oldIndex, new_index: newIndex })
  }, [send])

  const addDelay = useCallback((ms: number) => {
    send('add_delay', { delay_ms: ms })
  }, [send])

  const editDelay = useCallback((index: number, ms: number) => {
    send('edit_delay', { index, delay_ms: ms })
  }, [send])

  const sendAll = useCallback(() => {
    send('send')
  }, [send])

  const abortSend = useCallback(() => {
    send('abort')
  }, [send])

  const approveGuard = useCallback(() => {
    send('guard_approve')
    setGuardConfirm(null)
  }, [send])

  const rejectGuard = useCallback(() => {
    send('guard_reject')
    setGuardConfirm(null)
  }, [send])

  return {
    queue, summary, history, sendProgress, guardConfirm, error, connected,
    queueCommand, queueBuilt, deleteItem, clearQueue, undoLast,
    toggleGuard, reorder, addDelay, editDelay,
    sendAll, abortSend, approveGuard, rejectGuard,
  }
}
