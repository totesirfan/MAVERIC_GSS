import { useState, useEffect, useRef, useCallback } from 'react'
import { Play, Pause, Square, Gauge } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { colors } from '@/lib/colors'
import type { RxPacket } from '@/lib/types'

type LogEntry = Record<string, unknown>

const SPEEDS = [1, 2, 5, 10] as const
type Speed = typeof SPEEDS[number]

interface ReplayPanelProps {
  sessionId: string
  replacePackets: (pkts: RxPacket[]) => void
  onStop: () => void
}

/** Normalize a log entry into an RxPacket for display in the packet list */
function entryToPacket(e: LogEntry, index: number): RxPacket {
  return {
    num: (e.num as number) ?? index + 1,
    time: String(e.time ?? ''),
    time_utc: String(e.time_utc ?? ''),
    frame: String(e.frame ?? ''),
    size: (e.size as number) ?? 0,
    raw_hex: String(e.raw_hex ?? ''),
    warnings: (Array.isArray(e.warnings) ? e.warnings : []) as string[],
    is_echo: (e.is_echo as boolean) ?? false,
    is_dup: (e.is_dup as boolean) ?? false,
    is_unknown: (e.is_unknown as boolean) ?? false,
    ...(e._rendering && typeof e._rendering === 'object'
      ? { _rendering: e._rendering as RxPacket['_rendering'] }
      : {}),
  }
}

/** Parse a packet timestamp into a monotonic replay time.
 *  Uses full date+time when present so sessions spanning midnight replay correctly.
 */
function parseReplayTime(pkt: RxPacket): number {
  const raw = (pkt.time_utc || pkt.time || '').trim()
  if (!raw) return 0

  if (raw.length > 10 && raw[10] === 'T') {
    const iso = Date.parse(raw)
    if (!Number.isNaN(iso)) return iso
  }

  const full = raw.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?/)
  if (full) {
    const [, y, mo, d, h, mi, s, ms] = full
    return Date.UTC(
      Number(y), Number(mo) - 1, Number(d),
      Number(h), Number(mi), Number(s),
      Number((ms ?? '0').padEnd(3, '0').slice(0, 3)),
    )
  }

  const parts = raw.split(':')
  if (parts.length < 2) return 0
  const h = parseInt(parts[0], 10) || 0
  const m = parseInt(parts[1], 10) || 0
  const sparts = (parts[2] ?? '0').split('.')
  const s = parseInt(sparts[0], 10) || 0
  const ms = parseInt((sparts[1] ?? '0').padEnd(3, '0').slice(0, 3), 10) || 0
  return h * 3600000 + m * 60000 + s * 1000 + ms
}

export function ReplayPanel({ sessionId, replacePackets, onStop }: ReplayPanelProps) {
  const [allEntries, setAllEntries] = useState<RxPacket[]>([])
  const [, setIntervals] = useState<number[]>([])
  const [position, setPosition] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<Speed>(1)
  const [loading, setLoading] = useState(true)

  const posRef = useRef(0)
  const playingRef = useRef(false)
  const speedRef = useRef<Speed>(1)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const entriesRef = useRef<RxPacket[]>([])
  const intervalsRef = useRef<number[]>([])

  // Sync refs
  useEffect(() => { playingRef.current = playing }, [playing])
  useEffect(() => { speedRef.current = speed }, [speed])

  // Fetch session data
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setLoading(true)
    fetch(`/api/logs/${sessionId}`)
      .then((r) => r.json())
      .then((data: LogEntry[]) => {
        const packets = data.map((e, i) => entryToPacket(e, i))
        // Compute intervals from timestamps
        // Group packets with the same second and spread them evenly
        const gaps: number[] = [0]
        for (let i = 1; i < packets.length; i++) {
          const prevMs = parseReplayTime(packets[i - 1])
          const currMs = parseReplayTime(packets[i])
          const diff = currMs - prevMs
          if (diff > 0) {
            // Different seconds — use actual time gap, clamped to 10s max
            gaps.push(Math.min(diff, 10000))
          } else {
            // Same second — count how many packets share this second, spread evenly
            let runEnd = i + 1
            while (runEnd < packets.length && parseReplayTime(packets[runEnd]) === currMs) runEnd++
            const runSize = runEnd - i + 1
            gaps.push(Math.max(50, 1000 / runSize))
          }
        }
        setAllEntries(packets)
        entriesRef.current = packets
        setIntervals(gaps)
        intervalsRef.current = gaps
        setPosition(0)
        posRef.current = 0
        setPlaying(true)
        setLoading(false)
        // Immediately show first packet
        if (packets.length > 0) {
          replacePackets([packets[0]])
        }
      })
      .catch(() => { setLoading(false) })

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [sessionId, replacePackets])
  /* eslint-enable react-hooks/set-state-in-effect */

  // Replay tick engine — use ref for recursive call to avoid self-reference before declaration
  const scheduleNextRef = useRef<() => void>(() => {})
  const scheduleNext = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)

    const pos = posRef.current
    const entries = entriesRef.current
    const gaps = intervalsRef.current

    if (pos >= entries.length - 1 || !playingRef.current) return

    const nextPos = pos + 1
    const delay = gaps[nextPos] / speedRef.current

    timerRef.current = setTimeout(() => {
      posRef.current = nextPos
      setPosition(nextPos)
      replacePackets(entries.slice(0, nextPos + 1))
      scheduleNextRef.current()
    }, delay)
  }, [replacePackets])
  useEffect(() => { scheduleNextRef.current = scheduleNext }, [scheduleNext])

  // Start/stop playback
  useEffect(() => {
    if (playing && allEntries.length > 0 && position < allEntries.length - 1) {
      scheduleNext()
    } else {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [playing, scheduleNext, allEntries.length, position])

  const handlePlayPause = useCallback(() => {
    setPlaying((v) => !v)
  }, [])

  const handleStop = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setPlaying(false)
    onStop()
  }, [onStop])

  const cycleSpeed = useCallback(() => {
    setSpeed((prev) => {
      const idx = SPEEDS.indexOf(prev)
      return SPEEDS[(idx + 1) % SPEEDS.length]
    })
  }, [])

  const handleScrub = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const newPos = parseInt(e.target.value, 10)
    posRef.current = newPos
    setPosition(newPos)
    replacePackets(entriesRef.current.slice(0, newPos + 1))
    // If playing, restart the schedule from the new position
    if (playingRef.current) {
      if (timerRef.current) clearTimeout(timerRef.current)
      scheduleNext()
    }
  }, [replacePackets, scheduleNext])

  const atEnd = position >= allEntries.length - 1
  const total = allEntries.length

  // Auto-pause at end
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (atEnd && playing) {
      setPlaying(false)
    }
  }, [atEnd, playing])
  /* eslint-enable react-hooks/set-state-in-effect */

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0" style={{ borderColor: colors.borderSubtle, backgroundColor: `${colors.warning}08` }}>
        <span className="text-xs" style={{ color: colors.warning }}>Loading session...</span>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0" style={{ borderColor: `${colors.warning}44`, backgroundColor: `${colors.warning}0a` }}>
      {/* Play/Pause */}
      <Button variant="ghost" size="icon" className="size-6 shrink-0" onClick={handlePlayPause} title={playing ? 'Pause' : 'Play'}>
        {playing ? (
          <Pause className="size-3.5" style={{ color: colors.warning }} />
        ) : (
          <Play className="size-3.5" style={{ color: colors.success }} />
        )}
      </Button>

      {/* Stop */}
      <Button variant="ghost" size="icon" className="size-6 shrink-0" onClick={handleStop} title="Stop replay">
        <Square className="size-3" style={{ color: colors.error }} />
      </Button>

      {/* Speed */}
      <Button variant="ghost" size="sm" className="h-6 px-1.5 shrink-0 gap-1" onClick={cycleSpeed} title="Cycle speed">
        <Gauge className="size-3" style={{ color: colors.dim }} />
        <span className="text-[11px] font-bold tabular-nums" style={{ color: colors.value }}>{speed}x</span>
      </Button>

      {/* Scrubber */}
      <input
        type="range"
        min={0}
        max={Math.max(0, total - 1)}
        value={position}
        onChange={handleScrub}
        className="flex-1 h-1 accent-amber-400 cursor-pointer"
        style={{ accentColor: colors.warning }}
      />

      {/* Position counter */}
      <span className="text-[11px] tabular-nums shrink-0" style={{ color: colors.dim }}>
        {position + 1}/{total}
      </span>
    </div>
  )
}
