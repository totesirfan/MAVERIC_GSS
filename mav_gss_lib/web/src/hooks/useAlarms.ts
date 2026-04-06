import { useState, useRef, useCallback, useMemo } from 'react'
import type { RxPacket, RxStatus } from '@/lib/types'

export interface Alarm {
  id: string
  label: string
  detail: string
  severity: 'danger' | 'warning' | 'advisory'
  triggeredAt: number
}

const STALE_THRESHOLD_S = 60
const CRC_THRESHOLD = 3
const NONE_THRESHOLD = 3
const DUP_THRESHOLD = 5
const WINDOW_MS = 60_000

export function useAlarms(
  status: RxStatus,
  packets: RxPacket[],
  replayMode: boolean,
): {
  alarms: Alarm[]
  ackAll: () => void
  ackOne: (id: string) => void
} {
  const [ackedSet, setAckedSet] = useState<Set<string>>(new Set())
  const clearedSinceAck = useRef<Set<string>>(new Set())

  // Sliding window timestamps for packet-based alarms
  const crcTimes = useRef<number[]>([])
  const noneTimes = useRef<number[]>([])
  const dupTimes = useRef<number[]>([])
  const prevLen = useRef(0)

  // Update sliding windows when new packets arrive
  if (packets.length > prevLen.current) {
    const newPkts = packets.slice(prevLen.current)
    const now = Date.now()
    for (const p of newPkts) {
      if (p.crc16_ok === false) crcTimes.current.push(now)
      if (p.ptype === 'NONE' || p.ptype === '0') noneTimes.current.push(now)
      if (p.is_dup) dupTimes.current.push(now)
    }
    prevLen.current = packets.length
  }

  const alarms = useMemo<Alarm[]>(() => {
    if (replayMode) return []

    const now = Date.now()
    const cutoff = now - WINDOW_MS

    crcTimes.current = crcTimes.current.filter(t => t > cutoff)
    noneTimes.current = noneTimes.current.filter(t => t > cutoff)
    dupTimes.current = dupTimes.current.filter(t => t > cutoff)

    const candidates: Alarm[] = []

    if (status.silence_s >= STALE_THRESHOLD_S) {
      candidates.push({
        id: 'stale', label: 'STALE',
        detail: `no packet for ${status.silence_s.toFixed(0)}s`,
        severity: 'danger', triggeredAt: now,
      })
    }

    if (status.zmq === 'DOWN') {
      candidates.push({
        id: 'zmq_down', label: 'ZMQ DOWN',
        detail: 'ZMQ socket disconnected',
        severity: 'danger', triggeredAt: now,
      })
    }

    if (status.zmq === 'RETRY') {
      candidates.push({
        id: 'zmq_retry', label: 'ZMQ RETRY',
        detail: 'ZMQ socket reconnecting',
        severity: 'warning', triggeredAt: now,
      })
    }

    const crcCount = crcTimes.current.length
    if (crcCount >= CRC_THRESHOLD) {
      candidates.push({
        id: 'crc', label: 'CRC',
        detail: `${crcCount} errors in 60s`,
        severity: 'warning', triggeredAt: now,
      })
    }

    const noneCount = noneTimes.current.length
    if (noneCount >= NONE_THRESHOLD) {
      candidates.push({
        id: 'none_frames', label: 'NONE',
        detail: `${noneCount} unparseable in 60s`,
        severity: 'advisory', triggeredAt: now,
      })
    }

    const dupCount = dupTimes.current.length
    if (dupCount >= DUP_THRESHOLD) {
      candidates.push({
        id: 'dup', label: 'DUP',
        detail: `${dupCount} duplicates in 60s`,
        severity: 'advisory', triggeredAt: now,
      })
    }

    // Track cleared alarms for re-trigger logic
    const activeIds = new Set(candidates.map(a => a.id))
    for (const id of ackedSet) {
      if (!activeIds.has(id)) {
        clearedSinceAck.current.add(id)
      }
    }

    // Filter: remove acked alarms that haven't cleared and re-triggered
    const filtered = candidates.filter(a => {
      if (!ackedSet.has(a.id)) return true
      return clearedSinceAck.current.has(a.id)
    })

    const order: Record<string, number> = { danger: 0, warning: 1, advisory: 2 }
    filtered.sort((a, b) => order[a.severity] - order[b.severity])

    return filtered
  }, [status.silence_s, status.zmq, packets.length, replayMode, ackedSet])

  const ackAll = useCallback(() => {
    const ids = alarms.map(a => a.id)
    setAckedSet(prev => {
      const next = new Set(prev)
      ids.forEach(id => next.add(id))
      return next
    })
    clearedSinceAck.current = new Set()
  }, [alarms])

  const ackOne = useCallback((id: string) => {
    setAckedSet(prev => {
      const next = new Set(prev)
      next.add(id)
      return next
    })
    clearedSinceAck.current.delete(id)
  }, [])

  return { alarms, ackAll, ackOne }
}
