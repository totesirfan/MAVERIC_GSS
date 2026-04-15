import { useMemo, useRef, useEffect, useCallback } from 'react'
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso'
import { PacketRow } from './PacketRow'
import { colors } from '@/lib/colors'
import type { ColumnDef, GssConfig, RxPacket } from '@/lib/types'

interface PacketListProps {
  packets: RxPacket[]
  columns?: ColumnDef[]
  nodeDescriptions?: GssConfig['node_descriptions']
  showFrame: boolean
  showEcho: boolean
  flashPacketNum?: number | null
  selectedNum: number | null
  onSelect: (num: number) => void
  autoScroll: boolean
  onScrolledUp: () => void
  zmqStatus?: string
  scrollSignal?: number
  compact?: boolean
}

const MAX_DOM_PACKETS = 5000
const SCROLL_SUPPRESS_MS = 120
const BOTTOM_SCROLL_GUTTER_PX = 8
const BOTTOM_UNLOCK_THRESHOLD_PX = BOTTOM_SCROLL_GUTTER_PX + 8

export function PacketList({
  packets, columns, nodeDescriptions, showFrame, showEcho, flashPacketNum, selectedNum, onSelect,
  autoScroll, onScrolledUp, zmqStatus, scrollSignal, compact,
}: PacketListProps) {
  const isStale = zmqStatus ? ['DOWN', 'OFFLINE'].includes(zmqStatus.toUpperCase()) : false
  const virtuosoRef = useRef<VirtuosoHandle | null>(null)
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const suppressScroll = useRef(true)
  const suppressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const filtered = useMemo(
    () => (packets.length > MAX_DOM_PACKETS ? packets.slice(-MAX_DOM_PACKETS) : packets),
    [packets],
  )

  const scrollToBottom = useCallback(() => {
    const index = filtered.length - 1
    if (index < 0) return
    virtuosoRef.current?.scrollToIndex({
      index,
      align: 'end',
      behavior: 'auto',
    })
    requestAnimationFrame(() => {
      virtuosoRef.current?.scrollToIndex({
        index,
        align: 'end',
        behavior: 'auto',
      })
    })
  }, [filtered.length])

  // Auto-scroll to bottom when new packets arrive or container resizes
  useEffect(() => {
    if (autoScroll && filtered.length > 0) {
      suppressScroll.current = true
      if (suppressTimerRef.current) clearTimeout(suppressTimerRef.current)
      scrollToBottom()
      suppressTimerRef.current = setTimeout(() => {
        suppressScroll.current = false
        suppressTimerRef.current = null
      }, SCROLL_SUPPRESS_MS)
    }
  }, [filtered.length, autoScroll, scrollSignal, scrollToBottom])

  useEffect(() => {
    return () => {
      if (suppressTimerRef.current) clearTimeout(suppressTimerRef.current)
    }
  }, [])

  useEffect(() => {
    const el = viewportRef.current
    if (!el || !autoScroll || filtered.length === 0) return

    let frameA = 0
    let frameB = 0
    const observer = new ResizeObserver(() => {
      frameA = requestAnimationFrame(() => {
        scrollToBottom()
        frameB = requestAnimationFrame(() => {
          scrollToBottom()
        })
      })
    })

    observer.observe(el)

    return () => {
      observer.disconnect()
      if (frameA) cancelAnimationFrame(frameA)
      if (frameB) cancelAnimationFrame(frameB)
    }
  }, [autoScroll, filtered.length, scrollToBottom])

  // Detect user scrolling up to unlock — ignore programmatic scrolls
  const handleBottomStateChange = useCallback((isAtBottom: boolean) => {
    if (suppressScroll.current) return
    if (!isAtBottom) {
      onScrolledUp()
    }
  }, [onScrolledUp])

  return (
    <>
      {isStale && (
        <div className="flex items-center justify-center gap-2 px-3 py-1 text-xs font-semibold shrink-0"
          style={{ backgroundColor: colors.dangerFill, color: colors.danger, borderBottom: `1px solid ${colors.danger}40` }}>
          ⚠ DATA STALE — ZMQ disconnected
        </div>
      )}

      {filtered.length > 0 && (
        <div className="flex items-center text-[11px] font-light px-2 py-0.5 shrink-0" style={{ color: colors.sep }}>
          {!compact && <span className="w-5 px-1" />}
          {(columns ?? []).length > 0 ? (
            columns!.map(c => {
              if (c.toggle === 'showFrame' && !showFrame) return null
              if (c.toggle === 'showEcho' && !showEcho) return null
              return (
                <span
                  key={c.id}
                  className={`px-2 shrink-0 ${c.flex ? 'flex-1' : ''} ${c.align === 'right' ? 'text-right' : ''} ${c.width ?? ''}`}
                >
                  {c.label}
                </span>
              )
            })
          ) : (
            <>
              <span className="w-9 px-2 text-right">#</span>
              <span className="w-[68px] px-2">time</span>
              {showFrame && <span className="w-[72px] px-2">frame</span>}
              <span className="w-[52px] px-1.5">src</span>
              {showEcho && <span className="w-[52px] px-1.5">echo</span>}
              <span className="w-[52px] px-1">type</span>
              <span className="flex-1 px-2">id / args</span>
              <span className="w-[72px] px-2 text-right"></span>
              <span className="w-10 px-2 text-right">size</span>
            </>
          )}
        </div>
      )}

      {filtered.length === 0 ? (
        <div className="flex-1 flex items-center justify-center" style={{ color: colors.dim }}>
          <span className="text-xs py-8">Idle — no packets received</span>
        </div>
      ) : (
        <div ref={viewportRef} className="flex-1 min-h-0">
          <Virtuoso
            ref={virtuosoRef}
            className="h-full overflow-x-hidden"
            data={filtered}
            atBottomStateChange={handleBottomStateChange}
            atBottomThreshold={BOTTOM_UNLOCK_THRESHOLD_PX}
            overscan={300}
            components={{
              Footer: () => <div style={{ height: BOTTOM_SCROLL_GUTTER_PX }} aria-hidden="true" />,
            }}
            computeItemKey={(_, pkt) => pkt.num}
            itemContent={(_, pkt) => {
              const isActive = !compact && selectedNum === pkt.num
              const wrapClasses = compact
                ? `${pkt.num === flashPacketNum ? 'pkt-flash' : ''}`
                : `pkt-row-wrap ${pkt.num === flashPacketNum ? 'pkt-flash' : ''} ${isActive ? 'pkt-border-active' : 'pkt-border-inactive'}`
              return (
                <div className={wrapClasses}>
                  <PacketRow
                    packet={pkt}
                    columns={columns}
                    nodeDescriptions={nodeDescriptions}
                    selected={isActive}
                    showFrame={showFrame}
                    showEcho={showEcho}
                    compact={compact}
                    onClick={() => onSelect(pkt.num)}
                  />
                </div>
              )
            }}
          />
        </div>
      )}
    </>
  )
}
