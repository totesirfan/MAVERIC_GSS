import { useState, useEffect, useRef } from 'react'
import { ArrowDownToLine, Radio, Clock, Film } from 'lucide-react'
import { colors } from '@/lib/colors'
import type { RxPacket, RxStatus } from '@/lib/types'

interface RxStatusBarProps {
  status: RxStatus
  packets: RxPacket[]
  autoScroll: boolean
  onLiveClick: () => void
  replayMode?: boolean
}

const RECEIVE_TIMEOUT_MS = 2000

function ageColor(silence_s: number): string {
  if (silence_s >= 60) return colors.danger
  if (silence_s >= 30) return colors.warning
  return colors.textMuted
}

export function RxStatusBar({ status, packets, autoScroll, onLiveClick, replayMode }: RxStatusBarProps) {
  const [receiving, setReceiving] = useState(false)
  const [burstCount, setBurstCount] = useState(0)
  const prevCount = useRef(packets.length)
  const burstStart = useRef(0)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (packets.length > prevCount.current) {
      if (!receiving) {
        burstStart.current = prevCount.current
        setReceiving(true)
      }
      setBurstCount(packets.length - burstStart.current)

      if (timeoutRef.current) clearTimeout(timeoutRef.current)
      timeoutRef.current = setTimeout(() => setReceiving(false), RECEIVE_TIMEOUT_MS)
    }
    prevCount.current = packets.length
  }, [packets.length, receiving])
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    return () => { if (timeoutRef.current) clearTimeout(timeoutRef.current) }
  }, [])

  const crcCount = packets.filter(p =>
    p._rendering?.integrity_blocks?.some(b => b.ok === false)
  ).length
  const dupCount = packets.filter(p => p.is_dup).length

  if (replayMode) {
    return (
      <div
        className="rounded-lg border text-xs font-mono transition-all h-[62px] flex"
        style={{
          borderColor: `${colors.warning}55`,
          backgroundColor: `${colors.warning}10`,
        }}
      >
        <div className="flex items-center justify-between px-3 flex-1 relative z-10">
          <div className="flex items-center gap-2">
            <Film className="size-4 animate-pulse" style={{ color: colors.warning }} />
            <span className="font-bold" style={{ color: colors.warning }}>REPLAY</span>
            <span style={{ color: colors.warning }}>Session playback</span>
          </div>
          <div className="flex items-center gap-3">
            <span style={{ color: colors.textMuted }}>{packets.length} pkts</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div
      className={`rounded-lg border text-xs font-mono transition-all h-[62px] flex ${receiving ? 'animate-sweep-green animate-pulse-green' : 'animate-sweep-dim'}`}
      style={{
        borderColor: receiving ? `${colors.success}55` : colors.borderSubtle,
        backgroundColor: receiving ? `${colors.success}10` : colors.bgApp,
      }}
    >
      <div className="flex items-center justify-between px-3 flex-1 relative z-10">
        <div className="flex items-center gap-2">
          {receiving ? (
            <>
              <Radio className="size-4 animate-pulse-green-text" style={{ color: colors.success }} />
              <span className="font-bold" style={{ color: colors.success }}>Received</span>
              <span className="tabular-nums" style={{ color: colors.success }}>{burstCount} pkts</span>
            </>
          ) : (
            <>
              <Clock className="size-4" style={{ color: colors.textMuted }} />
              <span className="font-light" style={{ color: colors.textMuted }}>
                Idle — last packet{' '}
                <span className="tabular-nums" style={{ color: ageColor(status.silence_s) }}>
                  {status.silence_s.toFixed(0)}s ago
                </span>
              </span>
            </>
          )}
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="tabular-nums" style={{ color: colors.textMuted }}>{packets.length} pkts</span>
            {crcCount > 0 && (
              <span className="tabular-nums" style={{ color: `${colors.danger}99` }}>{crcCount} CRC</span>
            )}
            {dupCount > 0 && (
              <span className="tabular-nums" style={{ color: `${colors.warning}99` }}>{dupCount} dup</span>
            )}
          </div>
          {!autoScroll && (
            <button
              onClick={onLiveClick}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-medium color-transition hover:bg-white/[0.06] btn-feedback"
              style={{ color: colors.warning, border: `1px solid ${colors.warning}44` }}
            >
              <ArrowDownToLine className="size-3" />
              Scroll unlocked — click to resume
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
