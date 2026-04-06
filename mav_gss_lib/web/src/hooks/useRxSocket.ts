import { useEffect, useRef, useState, useCallback } from 'react'
import { createSocket } from '@/lib/ws'
import type { ColumnDef, RxPacket, RxStatus } from '@/lib/types'

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
  return Boolean(packet.echo && packet.echo !== 'NONE' && packet.echo !== '0')
}

export function useRxSocket() {
  const [packets, setPackets] = useState<RxPacket[]>([])
  const [status, setStatus] = useState<RxStatus>({ zmq: 'DOWN', pkt_rate: 0, silence_s: 0 })
  const [connected, setConnected] = useState(false)
  const [replayMode, setReplayMode] = useState(false)
  const [stats, setStats] = useState<RxPacketStats>(() => createEmptyStats())
  const [columns, setColumns] = useState<ColumnDef[]>([])
  const socketRef = useRef<ReturnType<typeof createSocket> | null>(null)
  const livePacketsRef = useRef<RxPacket[]>([])
  const replayRef = useRef(false)
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const statsRef = useRef<RxPacketStats>(createEmptyStats())

  const syncVisiblePackets = useCallback(() => {
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current)
      flushTimerRef.current = null
    }
    if (!replayRef.current) {
      setPackets([...livePacketsRef.current])
    }
    setStats({ ...statsRef.current })
  }, [])

  const scheduleFlush = useCallback(() => {
    if (flushTimerRef.current) return
    flushTimerRef.current = setTimeout(() => {
      syncVisiblePackets()
    }, FLUSH_INTERVAL_MS)
  }, [syncVisiblePackets])

  useEffect(() => {
    replayRef.current = replayMode
  }, [replayMode])

  useEffect(() => {
    const sock = createSocket(
      '/ws/rx',
      (data) => {
        const msg = data as Record<string, unknown>
        if (msg.type === 'columns' && msg.data) {
          setColumns(msg.data as ColumnDef[])
        } else if (msg.type === 'packet' && msg.data) {
          const pkt = msg.data as unknown as RxPacket
          livePacketsRef.current.push(pkt)
          const nextStats = statsRef.current
          nextStats.total += 1
          if (pkt.crc16_ok === false) nextStats.crcFailures += 1
          if (pkt.is_dup) nextStats.dupCount += 1
          if (!nextStats.hasEcho && packetHasEcho(pkt)) nextStats.hasEcho = true

          if (livePacketsRef.current.length > MAX_PACKETS) {
            const removed = livePacketsRef.current.shift()
            if (removed) {
              nextStats.total -= 1
              if (removed.crc16_ok === false) nextStats.crcFailures -= 1
              if (removed.is_dup) nextStats.dupCount -= 1
              if (nextStats.hasEcho && packetHasEcho(removed) && !livePacketsRef.current.some(packetHasEcho)) {
                nextStats.hasEcho = false
              }
            }
          }
          scheduleFlush()
        } else if (msg.type === 'status') {
          setStatus({
            zmq: (msg.zmq as string) || 'DOWN',
            pkt_rate: (msg.pkt_rate as number) || 0,
            silence_s: (msg.silence_s as number) || 0,
          })
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

  /** Replace displayed packets (used by replay to inject packets) */
  const replacePackets = useCallback((pkts: RxPacket[]) => {
    setPackets(pkts)
  }, [])

  /** Enter replay mode -- stashes live packets */
  const enterReplay = useCallback(() => {
    setReplayMode(true)
    setPackets([])
  }, [])

  /** Exit replay mode -- restores live packets */
  const exitReplay = useCallback(() => {
    setReplayMode(false)
    syncVisiblePackets()
  }, [syncVisiblePackets])

  return { packets, status, connected, stats, columns, clearPackets, replayMode, replacePackets, enterReplay, exitReplay }
}
