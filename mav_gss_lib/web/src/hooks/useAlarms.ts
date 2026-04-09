import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import type { RxPacket, RxStatus } from '@/lib/types'

export interface Alarm {
  id: string
  label: string
  detail: string
  severity: 'danger' | 'warning' | 'advisory'
  firstSeen: number
  lingering: boolean
  acked: boolean
}

const STALE_THRESHOLD_S = 60
const CRC_THRESHOLD = 3
const NONE_THRESHOLD = 3
const DUP_THRESHOLD = 5
const WINDOW_MS = 60_000
const LINGER_MS = 10_000

type AlarmSeverity = Alarm['severity']

const ALARM_META = {
  stale: { label: 'STALE', severity: 'danger' },
  zmq_down: { label: 'ZMQ DOWN', severity: 'danger' },
  zmq_retry: { label: 'ZMQ RETRY', severity: 'warning' },
  crc: { label: 'CRC', severity: 'warning' },
  none_frames: { label: 'NONE', severity: 'warning' },
  dup: { label: 'DUP', severity: 'advisory' },
} as const satisfies Record<string, { label: string; severity: AlarmSeverity }>

export function useAlarms(
  status: RxStatus,
  packets: RxPacket[],
  replayMode: boolean,
  sessionResetGen: number = 0,
): {
  alarms: Alarm[]
  ackAll: () => void
  ackOne: (id: string) => void
} {
  const [ackedSet, setAckedSet] = useState<Set<string>>(new Set())
  const clearedSinceAck = useRef<Set<string>>(new Set())

  // First-seen timestamps — persists as long as the alarm stays active or is lingering
  const firstSeenMap = useRef<Map<string, number>>(new Map())
  // When an alarm's condition clears, record the clear time for linger
  const clearedAtMap = useRef<Map<string, number>>(new Map())

  // Sliding window timestamps for packet-based alarms
  const crcTimes = useRef<number[]>([])
  const noneTimes = useRef<number[]>([])
  const dupTimes = useRef<number[]>([])
  const prevLen = useRef(0)

  // Reset all alarm state on session change
  useEffect(() => {
    if (sessionResetGen === 0) return // skip initial mount
    prevLen.current = 0
    crcTimes.current = []
    noneTimes.current = []
    dupTimes.current = []
    firstSeenMap.current = new Map()
    clearedAtMap.current = new Map()
    setAckedSet(new Set())
    clearedSinceAck.current = new Set()
  }, [sessionResetGen])

  // Force re-eval for linger expiry
  const [tick, setTick] = useState(0)
  const lingerTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  // Update sliding windows when new packets arrive
  useEffect(() => {
    if (packets.length > prevLen.current) {
      const newPkts = packets.slice(prevLen.current)
      const now = Date.now()
      for (const p of newPkts) {
        const flags = p._rendering?.row?.values?.flags
        const hasCrcFlag = Array.isArray(flags) && flags.some(
          (f: unknown) => typeof f === 'object' && f !== null && (f as Record<string, string>).tag === 'CRC',
        )
        if (hasCrcFlag) crcTimes.current.push(now)
        const ptype = p._rendering?.row?.values?.ptype
        if (ptype === 'NONE' || ptype === '0') noneTimes.current.push(now)
        if (p.is_dup) dupTimes.current.push(now)
      }
      prevLen.current = packets.length
    }
  }, [packets])

  // Tick every 2s to expire lingering alarms and update relative times
  useEffect(() => {
    lingerTimer.current = setInterval(() => setTick(t => t + 1), 2000)
    return () => { if (lingerTimer.current) clearInterval(lingerTimer.current) }
  }, [])

  /* eslint-disable react-hooks/exhaustive-deps */
  const alarms = useMemo<Alarm[]>(() => {
    if (replayMode) return []

    const now = Date.now()
    const cutoff = now - WINDOW_MS

    crcTimes.current = crcTimes.current.filter(t => t > cutoff)
    noneTimes.current = noneTimes.current.filter(t => t > cutoff)
    dupTimes.current = dupTimes.current.filter(t => t > cutoff)

    // Build active candidates (condition currently true)
    type ActiveAlarm = Omit<Alarm, 'firstSeen' | 'lingering' | 'acked'>
    const active: ActiveAlarm[] = []

    if (status.silence_s >= STALE_THRESHOLD_S) {
      active.push({
        id: 'stale', label: ALARM_META.stale.label,
        detail: `no packet for ${status.silence_s.toFixed(0)}s`,
        severity: ALARM_META.stale.severity,
      })
    }

    if (status.zmq === 'DOWN') {
      active.push({
        id: 'zmq_down', label: ALARM_META.zmq_down.label,
        detail: 'ZMQ socket disconnected',
        severity: ALARM_META.zmq_down.severity,
      })
    }

    if (status.zmq === 'RETRY') {
      active.push({
        id: 'zmq_retry', label: ALARM_META.zmq_retry.label,
        detail: 'ZMQ socket reconnecting',
        severity: ALARM_META.zmq_retry.severity,
      })
    }

    const crcCount = crcTimes.current.length
    if (crcCount >= CRC_THRESHOLD) {
      active.push({
        id: 'crc', label: ALARM_META.crc.label,
        detail: `${crcCount} errors in 60s`,
        severity: ALARM_META.crc.severity,
      })
    }

    const noneCount = noneTimes.current.length
    if (noneCount >= NONE_THRESHOLD) {
      active.push({
        id: 'none_frames', label: ALARM_META.none_frames.label,
        detail: `${noneCount} unparseable in 60s`,
        severity: ALARM_META.none_frames.severity,
      })
    }

    const dupCount = dupTimes.current.length
    if (dupCount >= DUP_THRESHOLD) {
      active.push({
        id: 'dup', label: ALARM_META.dup.label,
        detail: `${dupCount} duplicates in 60s`,
        severity: ALARM_META.dup.severity,
      })
    }

    const activeIds = new Set(active.map(a => a.id))

    // Update firstSeen — set on first appearance, never overwritten while active/lingering
    for (const a of active) {
      if (!firstSeenMap.current.has(a.id)) {
        firstSeenMap.current.set(a.id, now)
      }
      // Condition is active again — remove any pending clear
      clearedAtMap.current.delete(a.id)
    }

    // Track cleared alarms for linger
    for (const [id] of firstSeenMap.current) {
      if (!activeIds.has(id) && !clearedAtMap.current.has(id)) {
        clearedAtMap.current.set(id, now)
      }
    }

    // Build final alarm list: active + lingering
    const result: Alarm[] = []

    // Active alarms
    for (const a of active) {
      result.push({
        ...a,
        firstSeen: firstSeenMap.current.get(a.id) ?? now,
        lingering: false,
        acked: ackedSet.has(a.id) && !clearedSinceAck.current.has(a.id),
      })
    }

    // Lingering alarms (condition cleared but within linger window)
    for (const [id, clearedAt] of clearedAtMap.current) {
      if (activeIds.has(id)) continue
      if (now - clearedAt > LINGER_MS) {
        // Linger expired — clean up
        clearedAtMap.current.delete(id)
        firstSeenMap.current.delete(id)
        continue
      }
      // Don't show if acked
      if (ackedSet.has(id)) {
        clearedAtMap.current.delete(id)
        firstSeenMap.current.delete(id)
        continue
      }
      const meta = ALARM_META[id as keyof typeof ALARM_META]
      const firstSeen = firstSeenMap.current.get(id) ?? clearedAt
      result.push({
        id,
        label: meta?.label ?? id.toUpperCase().replace('_', ' '),
        detail: 'cleared',
        severity: meta?.severity ?? 'advisory',
        firstSeen,
        lingering: true,
        acked: false,
      })
    }

    const order: Record<string, number> = { danger: 0, warning: 1, advisory: 2 }
    result.sort((a, b) => order[a.severity] - order[b.severity])

    return result
  }, [status.silence_s, status.zmq, packets.length, replayMode, ackedSet, tick])
  /* eslint-enable react-hooks/exhaustive-deps */

  // Track which acked alarms have cleared (side-effect outside useMemo)
  useEffect(() => {
    if (replayMode) return
    const activeIds = new Set(alarms.map(a => a.id))
    for (const id of ackedSet) {
      if (!activeIds.has(id)) {
        clearedSinceAck.current.add(id)
      }
    }
  }, [alarms, ackedSet, replayMode])

  const ackAll = useCallback(() => {
    const ids = alarms.map(a => a.id)
    setAckedSet(prev => {
      const next = new Set(prev)
      ids.forEach(id => next.add(id))
      return next
    })
    for (const id of ids) {
      clearedSinceAck.current.delete(id)
      clearedAtMap.current.delete(id)
      firstSeenMap.current.delete(id)
    }
  }, [alarms])

  const ackOne = useCallback((id: string) => {
    setAckedSet(prev => {
      const next = new Set(prev)
      next.add(id)
      return next
    })
    clearedSinceAck.current.delete(id)
    clearedAtMap.current.delete(id)
    firstSeenMap.current.delete(id)
  }, [])

  return { alarms, ackAll, ackOne }
}
