import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

export type AlarmSeverity = 'watch' | 'warning' | 'critical'
export type AlarmState = 'unacked_active' | 'acked_active' | 'unacked_cleared'
export type AlarmSourceKind = 'platform' | 'container' | 'parameter'

export interface Alarm {
  id: string
  source: AlarmSourceKind
  label: string
  detail: string
  severity: AlarmSeverity
  state: AlarmState
  firstSeenMs: number
  lastTransitionMs: number
}

interface ServerAlarm {
  id: string; source: AlarmSourceKind; label: string; detail: string
  severity: AlarmSeverity; state: AlarmState
  first_seen_ms: number; last_eval_ms: number; last_transition_ms: number
  context: Record<string, unknown>
}

interface SnapshotMsg { type: 'alarm_snapshot'; alarms: ServerAlarm[] }
interface ChangeMsg {
  type: 'alarm_change'
  event: ServerAlarm
  prev_state: string | null
  prev_severity: AlarmSeverity | null
  removed: boolean
  operator: string
}

function _toAlarm(a: ServerAlarm): Alarm {
  return {
    id: a.id, source: a.source, label: a.label, detail: a.detail,
    severity: a.severity, state: a.state,
    firstSeenMs: a.first_seen_ms, lastTransitionMs: a.last_transition_ms,
  }
}

export function useAlarms(): {
  alarms: Alarm[]
  ackAll: () => void
  ackOne: (id: string) => void
} {
  const [byId, setById] = useState<Map<string, Alarm>>(new Map())
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let cancelled = false
    let attempt = 0
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (cancelled) return
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${proto}//${window.location.host}/ws/alarms`)
      wsRef.current = ws

      ws.onopen = () => { attempt = 0 }
      ws.onmessage = (ev) => {
        let msg: SnapshotMsg | ChangeMsg
        try { msg = JSON.parse(ev.data) } catch { return }
        if (msg.type === 'alarm_snapshot') {
          setById(new Map(msg.alarms.map(a => [a.id, _toAlarm(a)])))
        } else if (msg.type === 'alarm_change') {
          setById(prev => {
            const next = new Map(prev)
            if (msg.removed) {
              next.delete(msg.event.id)
            } else {
              next.set(msg.event.id, _toAlarm(msg.event))
            }
            return next
          })
        }
      }
      const reconnect = () => {
        wsRef.current = null
        if (cancelled) return
        attempt += 1
        const delayMs = Math.min(30_000, 500 * 2 ** Math.min(attempt, 6))
        retryTimer = setTimeout(connect, delayMs)
      }
      ws.onclose = reconnect
      ws.onerror = () => { try { ws.close() } catch { /* swallow */ } }
    }

    connect()
    return () => {
      cancelled = true
      if (retryTimer) clearTimeout(retryTimer)
      wsRef.current?.close()
    }
  }, [])

  const alarms = useMemo<Alarm[]>(() => {
    const order: Record<AlarmSeverity, number> = { critical: 0, warning: 1, watch: 2 }
    return Array.from(byId.values()).sort((a, b) =>
      order[a.severity] - order[b.severity]
    )
  }, [byId])

  const ackOne = useCallback((id: string) => {
    wsRef.current?.send(JSON.stringify({ type: 'ack', id }))
  }, [])
  const ackAll = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: 'ack_all' }))
  }, [])

  return { alarms, ackAll, ackOne }
}
