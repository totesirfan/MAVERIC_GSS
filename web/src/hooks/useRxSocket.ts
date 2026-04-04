import { useEffect, useRef, useState, useCallback } from 'react'
import { createSocket } from '@/lib/ws'
import type { RxPacket, RxStatus } from '@/lib/types'

const MAX_PACKETS = 500

interface RxSocketMessage {
  type: string
  packet?: RxPacket
  status?: RxStatus
}

export function useRxSocket() {
  const [packets, setPackets] = useState<RxPacket[]>([])
  const [status, setStatus] = useState<RxStatus>({ zmq: 'DOWN', pkt_rate: 0, silence_s: 0 })
  const [connected, setConnected] = useState(false)
  const socketRef = useRef<ReturnType<typeof createSocket> | null>(null)

  useEffect(() => {
    const sock = createSocket(
      '/ws/rx',
      (data) => {
        const msg = data as RxSocketMessage
        if (msg.type === 'packet' && msg.packet) {
          setPackets((prev) => {
            const next = [...prev, msg.packet!]
            return next.length > MAX_PACKETS ? next.slice(-MAX_PACKETS) : next
          })
        } else if (msg.type === 'status' && msg.status) {
          setStatus(msg.status)
        }
      },
      setConnected,
    )
    socketRef.current = sock
    return () => sock.close()
  }, [])

  const clearPackets = useCallback(() => setPackets([]), [])

  return { packets, status, connected, clearPackets }
}
