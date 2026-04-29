import { useEffect, useRef, useState, useCallback } from 'react'
import { createSocket } from '@/lib/ws'
import { packetFlags } from '@/lib/rxPacket'
import type { RxPacket, RxStatus } from '@/lib/types'

const MAX_PACKETS = 5000
const FLUSH_INTERVAL_MS = 50

interface RxPacketStats {
  total: number
  crcFailures: number
  dupCount: number
  hasEcho: boolean
}

const EMPTY_STATS: RxPacketStats = {
  total: 0,
  crcFailures: 0,
  dupCount: 0,
  hasEcho: false,
}

function createEmptyStats(): RxPacketStats {
  return { ...EMPTY_STATS }
}

function packetHasEcho(packet: RxPacket): boolean {
  return packet.is_echo
}

function packetHasCrcFail(packet: RxPacket): boolean {
  return packetFlags(packet).some(f => f.tag === 'CRC')
}

export function useRxSocket() {
  const [packets, setPackets] = useState<RxPacket[]>([])
  const [status, setStatus] = useState<RxStatus>({ zmq: 'DOWN', pkt_rate: 0, silence_s: 0 })
  const [connected, setConnected] = useState(false)
  const [stats, setStats] = useState<RxPacketStats>(() => createEmptyStats())
  const socketRef = useRef<ReturnType<typeof createSocket> | null>(null)
  const livePacketsRef = useRef<RxPacket[]>([])
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const statsRef = useRef<RxPacketStats>(createEmptyStats())
  const customListenersRef = useRef<Set<(msg: Record<string, unknown>) => void>>(new Set())
  const [sessionGeneration, setSessionGeneration] = useState(0)
  const [sessionTag, setSessionTag] = useState('')
  const [blackoutUntil, setBlackoutUntil] = useState<number | null>(null)

  const syncVisiblePackets = useCallback(() => {
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current)
      flushTimerRef.current = null
    }
    setPackets([...livePacketsRef.current])
    setStats({ ...statsRef.current })
  }, [])

  const scheduleFlush = useCallback(() => {
    if (flushTimerRef.current) return
    flushTimerRef.current = setTimeout(() => {
      syncVisiblePackets()
    }, FLUSH_INTERVAL_MS)
  }, [syncVisiblePackets])

  useEffect(() => {
    const sock = createSocket(
      '/ws/rx',
      (data) => {
        const msg = data as Record<string, unknown>
        if (msg.type === 'packet' && msg.data) {
          const pkt = msg.data as unknown as RxPacket
          livePacketsRef.current.push(pkt)
          const nextStats = statsRef.current
          nextStats.total += 1
          if (packetHasCrcFail(pkt)) nextStats.crcFailures += 1
          if (pkt.is_dup) nextStats.dupCount += 1
          if (!nextStats.hasEcho && packetHasEcho(pkt)) nextStats.hasEcho = true

          if (livePacketsRef.current.length > MAX_PACKETS) {
            const removed = livePacketsRef.current.shift()
            if (removed) {
              nextStats.total -= 1
              if (packetHasCrcFail(removed)) nextStats.crcFailures -= 1
              if (removed.is_dup) nextStats.dupCount -= 1
              if (nextStats.hasEcho && packetHasEcho(removed) && !livePacketsRef.current.some(packetHasEcho)) {
                nextStats.hasEcho = false
              }
            }
          }
          scheduleFlush()
        } else if (msg.type === 'session_new') {
          livePacketsRef.current = []
          statsRef.current = createEmptyStats()
          setPackets([])
          setStats(createEmptyStats())
          setBlackoutUntil(null)
          setSessionTag((msg as Record<string, unknown>).session_tag as string ?? 'untitled')
          setSessionGeneration((msg as Record<string, unknown>).session_generation as number ?? 0)
        } else if (msg.type === 'session_renamed') {
          setSessionTag((msg as Record<string, unknown>).session_tag as string ?? 'untitled')
        } else if (msg.type === 'status') {
          setStatus({
            zmq: (msg.zmq as string) || 'DOWN',
            pkt_rate: (msg.pkt_rate as number) || 0,
            silence_s: (msg.silence_s as number) || 0,
          })
        } else if (msg.type === 'blackout') {
          const rawMs = (msg as { ms?: unknown }).ms
          const ms = typeof rawMs === 'number' ? rawMs : 0
          if (ms > 0) {
            setBlackoutUntil(performance.now() + ms)
          } else {
            // Explicit clear from the backend (operator disabled the feature
            // while a prior window was still running). Null the deadline so
            // the pill hides immediately instead of finishing the old countdown.
            setBlackoutUntil(null)
          }
        } else {
          for (const listener of customListenersRef.current) {
            listener(msg)
          }
        }
      },
      setConnected,
    )
    socketRef.current = sock
    return () => {
      if (flushTimerRef.current) clearTimeout(flushTimerRef.current)
      sock.close()
    }
  }, [scheduleFlush])

  const clearPackets = useCallback(() => {
    setPackets([])
    livePacketsRef.current = []
    statsRef.current = createEmptyStats()
    setStats(createEmptyStats())
  }, [])

  const subscribeCustom = useCallback((fn: (msg: Record<string, unknown>) => void) => {
    customListenersRef.current.add(fn)
    return () => { customListenersRef.current.delete(fn) }
  }, [])

  return { packets, status, connected, stats, clearPackets, sessionGeneration, sessionTag, subscribeCustom, blackoutUntil }
}
