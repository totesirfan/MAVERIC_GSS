import { useEffect, useRef, useState, useCallback } from 'react'
import { createSocket } from '@/lib/ws'
import { showToast } from '@/components/shared/overlays/StatusToast'
import type {
  TxQueueItem, TxQueueSummary, TxHistoryItem,
  SendProgress, GuardConfirm, CmdDisplay,
  CommandInstance,
} from '@/lib/types'

interface SendingSnapshot {
  active?: boolean
  total?: number
  idx?: number
  guarding?: boolean
  waiting?: boolean
}

export function useTxSocket() {
  const [queue, setQueue] = useState<TxQueueItem[]>([])
  const [summary, setSummary] = useState<TxQueueSummary>({ cmds: 0, guards: 0, est_time_s: 0 })
  const [history, setHistory] = useState<TxHistoryItem[]>([])
  const [sendProgress, setSendProgress] = useState<SendProgress | null>(null)
  const [guardConfirm, setGuardConfirm] = useState<GuardConfirm | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)
  const [verification, setVerification] = useState<Map<string, CommandInstance>>(new Map())
  const socketRef = useRef<ReturnType<typeof createSocket> | null>(null)
  const queueRef = useRef<TxQueueItem[]>([])

  // Keep queueRef in sync so reorder callback can access latest queue
  useEffect(() => { queueRef.current = queue }, [queue])

  useEffect(() => {
    const sock = createSocket(
      '/ws/tx',
      (data) => {
        const msg = data as Record<string, unknown>
        switch (msg.type) {
          case 'queue':
          case 'queue_update':
            if (msg.items) setQueue(msg.items as TxQueueItem[])
            if (msg.summary) setSummary(msg.summary as TxQueueSummary)
            if (msg.sending && typeof msg.sending === 'object') {
              const sending = msg.sending as SendingSnapshot
              if (sending.active) {
                setSendProgress(prev => ({
                  sent: prev?.sent ?? 0,
                  total: typeof sending.total === 'number' ? sending.total : (prev?.total ?? 0),
                  current: prev?.current ?? (sending.waiting ? 'delay' : (sending.guarding ? 'guard confirm' : 'send in progress')),
                  waiting: typeof sending.waiting === 'boolean' ? sending.waiting : prev?.waiting,
                }))
              } else {
                setSendProgress(null)
                setGuardConfirm(null)
              }
            }
            break
          case 'history':
            if (msg.items) setHistory(msg.items as TxHistoryItem[])
            break
          case 'sent':
            if (msg.data) setHistory(prev => [...prev, msg.data as TxHistoryItem])
            break
          case 'send_progress':
            setSendProgress({
              sent: msg.sent as number,
              total: msg.total as number,
              current: msg.current as string,
              waiting: msg.waiting as boolean | undefined,
            })
            break
          case 'send_complete':
          case 'send_aborted':
            setSendProgress(null)
            setGuardConfirm(null)
            break
          case 'guard_confirm':
            setGuardConfirm({
              index: msg.index as number,
              display: (msg.display ?? { title: '?' }) as CmdDisplay,
            })
            break
          case 'error': {
            const code = (msg.code || '') as string
            if (code === 'send_active' || code === 'window_open') {
              const text = (msg.message || msg.error || 'admission blocked') as string
              showToast(text, 'warning', 'tx')
              break
            }
            let errMsg = (msg.message || msg.error || 'Unknown error') as string
            const lower = errMsg.toLowerCase()
            if (lower.includes('extra args')) errMsg += ' — check command schema for expected arg count'
            else if (lower.includes('too large') || lower.includes('payload')) errMsg += ' — reduce args or split command'
            else if (lower.includes('unknown') || lower.includes('not found')) errMsg += ' — verify command name in schema'
            setError(errMsg)
            setTimeout(() => setError(null), 5000)
            break
          }
          case 'session_new':
            setHistory([])
            break
          case 'send_error': {
            const errMsg = (msg.error || 'Send failed') as string
            setError(errMsg)
            setSendProgress(null)
            setGuardConfirm(null)
            setTimeout(() => setError(null), 5000)
            break
          }
          case 'verification_update': {
            const inst = (msg.instance ?? null) as CommandInstance | null
            if (inst) {
              setVerification(prev => {
                const next = new Map(prev)
                next.set(inst.cmd_event_id, inst)
                return next
              })
            }
            break
          }
          case 'verification_restore': {
            // Initial snapshot sent on /ws/tx connect (all open instances at once).
            const list = (msg.instances ?? []) as CommandInstance[]
            setVerification(new Map(list.map(i => [i.cmd_event_id, i])))
            break
          }
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

  // queueCommand: send CLI text line
  const queueCommand = useCallback((input: string) => {
    send('queue', { input })
  }, [send])

  const queueMissionCmd = useCallback((payload: Record<string, unknown>) => {
    send('queue_mission_cmd', { payload })
  }, [send])

  // reorder: component passes (oldIndex, newIndex), backend expects {order: [...]}
  const reorder = useCallback((oldIndex: number, newIndex: number) => {
    const q = queueRef.current
    const order = q.map((_, i) => i)
    const [removed] = order.splice(oldIndex, 1)
    order.splice(newIndex, 0, removed)
    send('reorder', { order })
  }, [send])

  // addDelay: component passes (ms), backend expects {index, delay_ms}
  const addDelay = useCallback((ms: number) => {
    const q = queueRef.current
    send('add_delay', { index: q.length, delay_ms: ms })
  }, [send])

  return {
    queue, summary, history, sendProgress, guardConfirm, error, connected,
    verification,
    queueCommand,
    queueMissionCmd,
    deleteItem: useCallback((index: number) => send('delete', { index }), [send]),
    clearQueue: useCallback(() => send('clear'), [send]),
    undoLast: useCallback(() => send('undo'), [send]),
    toggleGuard: useCallback((index: number) => send('guard', { index }), [send]),
    reorder,
    addDelay,
    editDelay: useCallback((index: number, delayMs: number) => send('edit_delay', { index, delay_ms: delayMs }), [send]),
    sendAll: useCallback(() => send('send'), [send]),
    abortSend: useCallback(() => send('abort'), [send]),
    approveGuard: useCallback(() => { send('guard_approve'); setGuardConfirm(null) }, [send]),
    rejectGuard: useCallback(() => { send('guard_reject'); setGuardConfirm(null) }, [send]),
  }
}
