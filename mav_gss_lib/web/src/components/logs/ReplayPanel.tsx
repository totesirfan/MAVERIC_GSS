import { useState, useEffect, useRef, useCallback } from 'react'
import { Play, Pause, Square, Gauge, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { colors } from '@/lib/colors'
import type { RxPacket, RenderingData } from '@/lib/types'

type LogEntry = Record<string, unknown>

const SPEEDS = [1, 2, 5, 10] as const
type Speed = typeof SPEEDS[number]

const FETCH_LIMIT = 500
const PREFETCH_THRESHOLD = 100
const MAX_INTER_PACKET_MS = 60_000  // cap silent stretches at 60s of replay time

interface ReplayPanelProps {
  sessionId: string
  replacePackets: (pkts: RxPacket[]) => void
  onStop: () => void
}

function hhmmss(ts_iso: string | undefined, ts_ms: number | undefined): string {
  if (ts_iso) {
    const m = ts_iso.match(/T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,3}))?/)
    if (m) return m[2] ? `${m[1]}.${m[2].padEnd(3, '0')}` : m[1]
  }
  if (typeof ts_ms === 'number' && ts_ms > 0) {
    const d = new Date(ts_ms)
    const hh = String(d.getUTCHours()).padStart(2, '0')
    const mm = String(d.getUTCMinutes()).padStart(2, '0')
    const ss = String(d.getUTCSeconds()).padStart(2, '0')
    const ms = String(d.getUTCMilliseconds()).padStart(3, '0')
    return `${hh}:${mm}:${ss}.${ms}`
  }
  return '--:--:--'
}

function entryCmdId(e: LogEntry): string {
  const top = e.cmd_id
  if (typeof top === 'string' && top) return top
  const mission = e.mission as Record<string, unknown> | undefined
  const cmd = mission?.cmd as Record<string, unknown> | undefined
  const inner = cmd?.cmd_id
  return typeof inner === 'string' ? inner : ''
}

/** Map a saved rx_packet event into a RxPacket with a best-effort row cell set.
 *  The live RX list renders cells via mission-owned column defs — for replay we
 *  populate the common cell IDs (num, time, cmd, size, frame) from canonical
 *  fields so the list is readable without re-running mission rendering code. */
function entryToPacket(e: LogEntry, index: number): RxPacket {
  const seq = Number(e.seq ?? index + 1)
  const ts_ms = typeof e.ts_ms === 'number' ? e.ts_ms : undefined
  const ts_iso = typeof e.ts_iso === 'string' ? e.ts_iso : undefined
  const time = hhmmss(ts_iso, ts_ms)
  const cmdId = entryCmdId(e)
  const frame = String(e.frame_type ?? e.frame_label ?? '')
  const wireLen = Number(e.wire_len ?? 0)
  const warnings = (Array.isArray(e.warnings) ? e.warnings : []) as string[]

  const rendering: RenderingData = {
    row: {
      num: { value: seq },
      time: { value: time, monospace: true },
      cmd: { value: cmdId },
      size: { value: wireLen },
      frame: { value: frame },
    },
    detail_blocks: [],
    protocol_blocks: [],
    integrity_blocks: [],
    meta: {},
  }

  return {
    num: seq,
    time,
    time_utc: ts_iso ?? '',
    frame,
    size: wireLen,
    raw_hex: String(e.wire_hex ?? e.inner_hex ?? ''),
    warnings,
    is_echo: !!e.uplink_echo,
    is_dup: !!e.duplicate,
    is_unknown: !!e.unknown,
    _rendering: rendering,
  }
}

function cursorKey(sessionId: string): string {
  return `gss:replay:${sessionId}`
}

export function ReplayPanel({ sessionId, replacePackets, onStop }: ReplayPanelProps) {
  const [allEntries, setAllEntries] = useState<RxPacket[]>([])
  const [position, setPosition] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<Speed>(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [tooltipTime, setTooltipTime] = useState<string | null>(null)
  const [tooltipX, setTooltipX] = useState(0)
  const [dragging, setDragging] = useState(false)
  const scrubberRef = useRef<HTMLDivElement>(null)

  const posRef = useRef(0)
  const playingRef = useRef(false)
  const speedRef = useRef<Speed>(1)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const entriesRef = useRef<RxPacket[]>([])
  const tsMsRef = useRef<number[]>([])
  const offsetRef = useRef(0)
  const hasMoreRef = useRef(false)
  const fetchingRef = useRef(false)

  useEffect(() => { playingRef.current = playing }, [playing])
  useEffect(() => { speedRef.current = speed }, [speed])

  const appendPage = useCallback((rawEntries: LogEntry[]) => {
    const base = entriesRef.current.length
    const newPackets = rawEntries.map((e, i) => entryToPacket(e, base + i))
    const newTs = rawEntries.map((e) =>
      typeof e.ts_ms === 'number' ? e.ts_ms as number : 0,
    )
    entriesRef.current = [...entriesRef.current, ...newPackets]
    tsMsRef.current = [...tsMsRef.current, ...newTs]
    setAllEntries(entriesRef.current)
  }, [])

  const fetchPage = useCallback(async (offset: number): Promise<boolean> => {
    if (fetchingRef.current) return false
    fetchingRef.current = true
    try {
      const url = `/api/logs/${sessionId}?event_kind=rx_packet&offset=${offset}&limit=${FETCH_LIMIT}`
      const resp = await fetch(url)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json() as { entries: LogEntry[]; has_more: boolean }
      appendPage(data.entries)
      offsetRef.current = offset + data.entries.length
      hasMoreRef.current = !!data.has_more
      setHasMore(!!data.has_more)
      return true
    } catch (e) {
      setError(`Replay fetch failed: ${String(e)}`)
      return false
    } finally {
      fetchingRef.current = false
    }
  }, [sessionId, appendPage])

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setLoading(true)
    setError(null)
    entriesRef.current = []
    tsMsRef.current = []
    offsetRef.current = 0
    hasMoreRef.current = false

    fetchPage(0).then(() => {
      const saved = Number(sessionStorage.getItem(cursorKey(sessionId)) ?? 0)
      const startPos = Number.isFinite(saved) && saved > 0 && saved < entriesRef.current.length
        ? saved
        : 0
      posRef.current = startPos
      setPosition(startPos)
      setPlaying(true)
      setLoading(false)
      if (entriesRef.current.length > 0) {
        replacePackets(entriesRef.current.slice(0, startPos + 1))
      }
    })

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [sessionId, fetchPage, replacePackets])
  /* eslint-enable react-hooks/set-state-in-effect */

  // Persist cursor on position change
  useEffect(() => {
    sessionStorage.setItem(cursorKey(sessionId), String(position))
  }, [sessionId, position])

  // Gap (ms) between position p-1 and p, clamped to keep long silent stretches
  // from stalling replay. Uses the actual ts_ms difference — no per-second
  // smoothing, no 10s clamp — so packets replay with true relative timing.
  const gapMs = useCallback((p: number): number => {
    if (p <= 0) return 0
    const ts = tsMsRef.current
    if (!ts[p] || !ts[p - 1]) return 100
    const diff = ts[p] - ts[p - 1]
    if (diff <= 0) return 0
    return Math.min(diff, MAX_INTER_PACKET_MS)
  }, [])

  const scheduleNextRef = useRef<() => void>(() => {})
  const scheduleNext = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)

    const pos = posRef.current
    const entries = entriesRef.current

    if (!playingRef.current) return
    if (pos >= entries.length - 1) {
      // Streaming: try to fetch more before pausing
      if (hasMoreRef.current && !fetchingRef.current) {
        fetchPage(offsetRef.current).then(() => scheduleNextRef.current())
      }
      return
    }

    const nextPos = pos + 1
    // Prefetch next page as we approach the loaded tail
    if (hasMoreRef.current
        && !fetchingRef.current
        && entries.length - nextPos < PREFETCH_THRESHOLD) {
      fetchPage(offsetRef.current)
    }

    const delay = gapMs(nextPos) / speedRef.current

    timerRef.current = setTimeout(() => {
      posRef.current = nextPos
      setPosition(nextPos)
      replacePackets(entriesRef.current.slice(0, nextPos + 1))
      scheduleNextRef.current()
    }, delay)
  }, [replacePackets, fetchPage, gapMs])
  useEffect(() => { scheduleNextRef.current = scheduleNext }, [scheduleNext])

  useEffect(() => {
    if (playing && allEntries.length > 0 && position < allEntries.length - 1) {
      scheduleNext()
    } else if (timerRef.current) {
      clearTimeout(timerRef.current)
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [playing, scheduleNext, allEntries.length, position])

  const handlePlayPause = useCallback(() => setPlaying(v => !v), [])

  const handleStop = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setPlaying(false)
    sessionStorage.removeItem(cursorKey(sessionId))
    onStop()
  }, [onStop, sessionId])

  const cycleSpeed = useCallback(() => {
    setSpeed((prev) => SPEEDS[(SPEEDS.indexOf(prev) + 1) % SPEEDS.length])
  }, [])

  const handleScrub = useCallback((_value: number | readonly number[]) => {
    const raw = Array.isArray(_value) ? _value[0] ?? 0 : _value
    const idx = Math.round(raw)
    posRef.current = idx
    setPosition(idx)
    replacePackets(entriesRef.current.slice(0, idx + 1))
    if (playingRef.current) {
      if (timerRef.current) clearTimeout(timerRef.current)
      scheduleNext()
    }
  }, [replacePackets, scheduleNext])

  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (dragging) return
    const rect = scrubberRef.current?.getBoundingClientRect()
    const total = entriesRef.current.length
    if (!rect || total === 0) return
    const fraction = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const idx = Math.min(Math.round(fraction * (total - 1)), total - 1)
    setTooltipTime(entriesRef.current[idx]?.time || '--:--:--')
    setTooltipX(fraction * 100)
  }, [dragging])

  const handlePointerLeave = useCallback(() => setTooltipTime(null), [])

  const handleDragEnd = useCallback(() => {
    setDragging(false)
    const total = entriesRef.current.length
    if (total > 0) {
      const pos = posRef.current
      const fraction = total > 1 ? pos / (total - 1) : 0
      setTooltipTime(entriesRef.current[pos]?.time || '--:--:--')
      setTooltipX(fraction * 100)
    }
  }, [])

  const atEnd = position >= allEntries.length - 1 && !hasMore

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (atEnd && playing) setPlaying(false)
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
      <Button variant="ghost" size="icon" className="size-6 shrink-0" onClick={handlePlayPause} title={playing ? 'Pause' : 'Play'}>
        {playing ? (
          <Pause className="size-3.5" style={{ color: colors.warning }} />
        ) : (
          <Play className="size-3.5" style={{ color: colors.success }} />
        )}
      </Button>

      <Button variant="ghost" size="icon" className="size-6 shrink-0" onClick={handleStop} title="Stop replay">
        <Square className="size-3" style={{ color: colors.danger }} />
      </Button>

      <Button variant="ghost" size="sm" className="h-6 px-1.5 shrink-0 gap-1" onClick={cycleSpeed} title="Cycle speed">
        <Gauge className="size-3" style={{ color: colors.dim }} />
        <span className="text-[11px] font-bold tabular-nums" style={{ color: colors.value }}>{speed}x</span>
      </Button>

      {error && (
        <span className="text-[11px] flex items-center gap-1" style={{ color: colors.danger }}>
          <AlertTriangle className="size-3" />
          {error}
        </span>
      )}

      <div
        ref={scrubberRef}
        className="relative flex-1 group"
        onPointerMove={handlePointerMove}
        onPointerLeave={handlePointerLeave}
        onPointerUp={handleDragEnd}
        onPointerCancel={handleDragEnd}
      >
        {tooltipTime && (
          <div
            className="absolute -top-7 -translate-x-1/2 px-1.5 py-0.5 rounded text-[10px] font-mono tabular-nums pointer-events-none whitespace-nowrap"
            style={{
              left: `${tooltipX}%`,
              backgroundColor: colors.bgPanelRaised,
              color: colors.textSecondary,
              border: `1px solid ${colors.borderSubtle}`,
            }}
          >
            {tooltipTime}
          </div>
        )}
        <Slider
          min={0}
          max={Math.max(allEntries.length - 1, 1)}
          step={1}
          value={[position]}
          onValueChange={handleScrub}
          onPointerDown={() => { setDragging(true); setTooltipTime(null) }}
          onValueCommitted={handleDragEnd}
          data-dragging={dragging || undefined}
          style={{ '--slider-track': colors.borderSubtle } as React.CSSProperties}
          className="w-full cursor-pointer [&_[data-slot=slider-track]]:h-1 [&_[data-slot=slider-track]]:group-hover:h-1.5 [&_[data-slot=slider-track]]:transition-all [&_[data-slot=slider-track]]:bg-[var(--slider-track)] [&_[data-slot=slider-range]]:bg-amber-400 [&_[data-slot=slider-thumb]]:size-3 [&_[data-slot=slider-thumb]]:opacity-0 [&_[data-slot=slider-thumb]]:group-hover:opacity-100 [&[data-dragging]_[data-slot=slider-thumb]]:opacity-100 [&_[data-slot=slider-thumb]]:focus-visible:opacity-100 [&_[data-slot=slider-thumb]]:transition-opacity [&_[data-slot=slider-thumb]]:border-0 [&_[data-slot=slider-thumb]]:bg-amber-400"
        />
      </div>

      <span className="text-[11px] font-mono tabular-nums shrink-0" style={{ color: colors.dim }}>
        {allEntries.length > 0 ? (allEntries[position]?.time ?? '--:--:--') : '--:--:--'}
        {hasMore && <span className="ml-1 text-[10px]" style={{ color: colors.warning }}>+</span>}
      </span>
    </div>
  )
}
