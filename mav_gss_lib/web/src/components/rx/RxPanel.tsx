import { useState, useRef, useCallback, useMemo, useEffect } from 'react'
import { useRxToggles } from '@/hooks/useRxToggles'
import { useReceivingDetection } from '@/hooks/useReceivingDetection'
import { SessionBanner } from './SessionBanner'
import { AnimatePresence, motion } from 'framer-motion'
import { ExternalLink, SlidersHorizontal, ArrowDownToLine, Download, X, ClipboardCopy, Binary } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { TogglePill } from '@/components/shared/atoms/TogglePill'
import { StatusDot } from '@/components/shared/atoms/StatusDot'
import { PacketList } from './PacketList'
import { PacketDetail } from './PacketDetail'
import { BlackoutPill } from './BlackoutPill'
import { ReplayPanel } from '@/components/logs/ReplayPanel'
import { colors } from '@/lib/colors'
import { renderingText } from '@/lib/rendering'
import {
  ContextMenuRoot, ContextMenuTrigger, ContextMenuContent,
  ContextMenuItem,
} from '@/components/shared/overlays/ContextMenu'
import type { ColumnDef, GssConfig, RxPacket, RxStatus } from '@/lib/types'

function f(label: string, value: string): string {
  return `  ${label.padEnd(12)} ${value}`
}

/** Extract command label from _rendering (live row or replay detail_blocks). */
function extractCmd(p: RxPacket): string {
  const rowCmd = renderingText(p._rendering, 'cmd')
  if (rowCmd) return String(rowCmd).split(' ')[0] || '???'
  // Fallback: search command blocks
  for (const block of p._rendering?.detail_blocks ?? []) {
    if (block.kind !== 'command') continue
    for (const field of block.fields ?? []) {
      if (field.name === 'Command') return field.value || '???'
    }
  }
  return '???'
}

/** Extract "cmd args" string from _rendering for clipboard. */
function extractCmdArgs(p: RxPacket): string {
  const rowCmd = renderingText(p._rendering, 'cmd')
  if (rowCmd) return String(rowCmd).trim()
  // Fallback: build from command blocks only (not routing)
  const parts: string[] = []
  for (const block of p._rendering?.detail_blocks ?? []) {
    if (block.kind !== 'command') continue
    for (const field of block.fields ?? []) {
      parts.push(field.value)
    }
  }
  return parts.join(' ').trim()
}

function formatPacketText(p: RxPacket): string {
  const lines: string[] = []
  const sep = '\u2500'
  const extras = [p.frame || '', `${p.size}B`, p.is_dup ? '[DUP]' : '', p.is_echo ? '[UL]' : ''].filter(Boolean).join('  ')
  lines.push(`${sep.repeat(4)} #${p.num}  ${p.time_utc || p.time}  ${extras} ${sep.repeat(20)}`)
  if (p.is_echo) lines.push('  \u25B2\u25B2\u25B2 UPLINK ECHO \u25B2\u25B2\u25B2')
  for (const w of p.warnings) lines.push(f('\u26A0 WARNING', w))

  const r = p._rendering
  if (r?.detail_blocks) {
    for (const block of r.detail_blocks) {
      for (const field of block.fields ?? []) {
        lines.push(f(field.name.toUpperCase(), field.value))
      }
    }
  }

  if (r?.protocol_blocks) {
    for (const block of r.protocol_blocks) {
      const vals = (block.fields ?? []).map((fld: { name: string; value: string }) => `${fld.name}:${fld.value}`).join('  ')
      lines.push(f(block.label, vals))
    }
  }

  if (r?.integrity_blocks) {
    for (const block of r.integrity_blocks) {
      lines.push(f(block.label, block.ok === null ? '?' : block.ok ? 'OK' : 'FAIL'))
    }
  }

  if (p.raw_hex) {
    const hex = p.raw_hex.match(/.{1,2}/g)?.join(' ') ?? p.raw_hex
    const chunks = hex.match(/.{1,47}/g) ?? [hex]
    chunks.forEach((chunk, i) => lines.push(i === 0 ? f('HEX', chunk) : f('', chunk)))
  }
  return lines.join('\n')
}

interface RxPanelProps {
  config?: GssConfig | null
  packets: RxPacket[]
  status: RxStatus
  packetStats?: {
    total: number
    crcFailures: number
    dupCount: number
    hasEcho: boolean
  }
  columns?: ColumnDef[]
  replayMode?: boolean
  replaySession?: string | null
  replacePackets?: (pkts: RxPacket[]) => void
  onStopReplay?: () => void
  sessionGeneration?: number
  sessionTag?: string
  blackoutUntil?: number | null
  externalShowHex?: boolean
  externalShowFrame?: boolean
  externalShowWrapper?: boolean
  externalHideUplink?: boolean
  onToggleHex?: () => void
  onToggleFrame?: () => void
  onToggleWrapper?: () => void
  onToggleUplink?: () => void
}

function ageColor(s: number): string {
  if (s >= 210) return colors.danger
  if (s >= 180) return colors.warning
  return colors.textMuted
}

function hasEcho(packet: RxPacket): boolean {
  return packet.is_echo
}

export function RxPanel({ config, packets, status, packetStats, columns, replayMode, replaySession, replacePackets, onStopReplay, sessionGeneration, sessionTag, blackoutUntil, externalShowHex, externalShowFrame, externalShowWrapper, externalHideUplink, onToggleHex, onToggleFrame, onToggleWrapper, onToggleUplink }: RxPanelProps) {
  const { showHex, showFrame, showWrapper, hideUplink, toggleHex, toggleFrame, toggleWrapper, toggleUplink } = useRxToggles({
    externalShowHex, externalShowFrame, externalShowWrapper, externalHideUplink,
    onToggleHex, onToggleFrame, onToggleWrapper, onToggleUplink,
  })
  const [autoScroll, setAutoScroll] = useState(true)
  const [selectedNum, setSelectedNum] = useState<number | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailHeight, setDetailHeight] = useState(200)
  const [isDraggingState, setIsDraggingState] = useState(false)
  const isDragging = useRef(false)
  // Track whether user explicitly pinned a non-latest packet
  const pinned = useRef(false)

  const filtered = useMemo(
    () => hideUplink ? packets.filter(p => !p.is_echo) : packets,
    [packets, hideUplink],
  )
  const showEcho = useMemo(
    () => !hideUplink && (packetStats?.hasEcho ?? packets.some(hasEcho)),
    [hideUplink, packetStats?.hasEcho, packets],
  )
  const lastNum = filtered.length > 0 ? filtered[filtered.length - 1].num : null
  const lastPktNum = packets.length > 0 ? packets[packets.length - 1].num : -1
  const receiving = useReceivingDetection(lastPktNum)

  // Auto-follow latest
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (autoScroll && lastNum !== null && !pinned.current) {
      setSelectedNum(lastNum)
    }
  }, [autoScroll, lastNum])
  /* eslint-enable react-hooks/set-state-in-effect */

  function handleSelect(num: number) {
    if (selectedNum === num && detailOpen) {
      setDetailOpen(false)
      setSelectedNum(null)
    } else if (selectedNum === num && !detailOpen) {
      setDetailOpen(true)
    } else {
      setSelectedNum(num)
      setDetailOpen(true)
      if (num !== lastNum) {
        pinned.current = true
        setAutoScroll(false)
      } else {
        pinned.current = false
      }
    }
  }

  const handleScrolledUp = useCallback(() => setAutoScroll(false), [])

  const scrollToBottom = useCallback(() => {
    pinned.current = false
    setAutoScroll(true)
  }, [])

  const startDragResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDragging.current = true
    setIsDraggingState(true)
    const startY = e.clientY
    const startH = detailHeight
    function onMove(ev: MouseEvent) {
      setDetailHeight(Math.max(100, Math.min(window.innerHeight * 0.7, startH + (startY - ev.clientY))))
    }
    function onUp() {
      isDragging.current = false
      setIsDraggingState(false)
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [detailHeight])

  const handleResizeKey = useCallback((e: React.KeyboardEvent) => {
    const STEP = 40
    if (e.key === 'PageUp') {
      e.preventDefault()
      setDetailHeight(h => Math.min(window.innerHeight * 0.7, h + STEP))
    } else if (e.key === 'PageDown') {
      e.preventDefault()
      setDetailHeight(h => Math.max(100, h - STEP))
    } else if (e.key === 'Home') {
      e.preventDefault()
      setDetailHeight(200)
    }
  }, [])

  const selectedPacket = selectedNum !== null ? filtered.find(p => p.num === selectedNum) ?? null : null
  const isLive = autoScroll && selectedNum === lastNum
  const missionName = config?.mission.name ?? 'MAVERIC'

  return (
    <div className="flex flex-col h-full gap-3 relative">
      <div
        className="flex flex-col flex-1 min-h-0 rounded-lg border overflow-hidden shadow-panel"
        style={{
          borderColor: receiving ? `${colors.success}55` : colors.borderSubtle,
          backgroundColor: colors.bgPanel,
          transition: 'border-color 160ms ease',
        }}
      >
        <div
          className={`flex items-center justify-between px-3 py-1.5 border-b shrink-0 ${receiving ? 'animate-sweep-green' : ''}`}
          style={{
            borderColor: colors.borderSubtle,
            backgroundColor: receiving ? `${colors.success}08` : 'transparent',
            transition: 'background-color 160ms ease',
          }}
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold tracking-wide uppercase" style={{ color: colors.value }}>{config?.mission.config.rx_title ?? 'RX Downlink'}</span>
            <StatusDot status={replayMode ? 'REPLAY' : status.zmq} />
            {replayMode ? (
              <span className="text-[11px] font-medium" style={{ color: colors.warning }}>REPLAY</span>
            ) : receiving ? (
              <span className="text-[11px] font-bold animate-pulse-text flex items-center gap-1" style={{ color: colors.success }}>
                <Download className="size-3" />
                Received
              </span>
            ) : (
              <span className="text-[11px] font-light" style={{ color: colors.textMuted }}>
                Idle — last packet{' '}
                <span className="tabular-nums" style={{ color: ageColor(status.silence_s) }}>
                  {status.silence_s.toFixed(0)}s ago
                </span>
              </span>
            )}
            <BlackoutPill
              until={blackoutUntil ?? null}
              configuredMs={config?.platform.rx.tx_blackout_ms ?? 0}
            />
            {!replayMode && packets.length > 0 && (
              <span className="text-[11px] font-mono tabular-nums flex items-center gap-2 ml-auto mr-2" style={{ color: colors.textMuted }}>
                {packetStats?.total ?? packets.length} pkts
                {(packetStats?.crcFailures ?? 0) > 0 && (
                  <span style={{ color: `${colors.danger}99` }}>{packetStats?.crcFailures ?? 0} CRC</span>
                )}
                {(packetStats?.dupCount ?? 0) > 0 && (
                  <span style={{ color: `${colors.warning}99` }}>{packetStats?.dupCount ?? 0} dup</span>
                )}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1 group/toggles">
            <div className="flex items-center gap-1">
              <div className={`flex items-center gap-1 ${!showHex ? 'hidden group-hover/toggles:flex' : 'flex'}`}>
                <TogglePill label="HEX" active={showHex} onClick={toggleHex} />
              </div>
              <div className={`flex items-center gap-1 ${hideUplink ? 'hidden group-hover/toggles:flex' : 'flex'}`}>
                <TogglePill label="UL" active={!hideUplink} onClick={toggleUplink} />
              </div>
              <div className={`flex items-center gap-1 ${!showFrame ? 'hidden group-hover/toggles:flex' : 'flex'}`}>
                <TogglePill label="FRAME" active={showFrame} onClick={toggleFrame} />
              </div>
              <div className={`flex items-center gap-1 ${!showWrapper ? 'hidden group-hover/toggles:flex' : 'flex'}`}>
                <TogglePill label="WRAP" active={showWrapper} onClick={toggleWrapper} />
              </div>
            </div>
            {!showHex && hideUplink && !showFrame && !showWrapper && (
              <SlidersHorizontal className="size-3.5 group-hover/toggles:hidden" style={{ color: colors.dim }} />
            )}
            <Button variant="ghost" size="icon" className="size-6" onClick={() => window.open('/?panel=rx', `${missionName.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-rx`, 'popup=1,width=900,height=800')} title={`Pop out ${missionName} RX panel`}>
              <ExternalLink className="size-3.5" style={{ color: colors.dim }} />
            </Button>
          </div>
        </div>

        {replayMode && replaySession && replacePackets && onStopReplay && (
          <ReplayPanel sessionId={replaySession} replacePackets={replacePackets} onStop={onStopReplay} />
        )}

        <SessionBanner sessionGeneration={sessionGeneration} sessionTag={sessionTag} packetCount={packets.length} />

        <PacketList
          packets={filtered}
          columns={columns}
          showFrame={showFrame}
          showEcho={showEcho}
          flashPacketNum={lastNum}
          selectedNum={selectedNum}
          onSelect={handleSelect}
          autoScroll={autoScroll}
          onScrolledUp={handleScrolledUp}
          zmqStatus={replayMode ? 'REPLAY' : status.zmq}
          scrollSignal={detailOpen ? detailHeight : -1}
        />

        {!autoScroll && (
          <button
            onClick={scrollToBottom}
            className="flex items-center justify-center gap-1.5 px-3 py-1 text-[11px] font-medium shrink-0 color-transition hover:bg-white/[0.04] btn-feedback"
            style={{ color: colors.warning, backgroundColor: `${colors.warning}08`, borderTop: `1px solid ${colors.warning}22` }}
          >
            <ArrowDownToLine className="size-3" />
            Scroll unlocked — click to resume
          </button>
        )}
      </div>

      {selectedPacket && (
        <div
          className="shrink-0 overflow-hidden"
          style={{
            height: detailOpen ? detailHeight : 0,
            opacity: detailOpen ? 1 : 0,
            transition: isDraggingState ? 'none' : 'height 0.2s ease, opacity 0.15s ease',
          }}
        >
          <ContextMenuRoot>
            <ContextMenuTrigger>
              <div
                className="flex flex-col rounded-lg border overflow-hidden shadow-panel"
                style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel, height: detailHeight }}
              >
                <div
                  onMouseDown={startDragResize}
                  onKeyDown={handleResizeKey}
                  role="separator"
                  aria-orientation="horizontal"
                  aria-label="Resize packet detail pane — PageUp/PageDown to adjust, Home to reset"
                  title="Drag to resize · PageUp/PageDown"
                  tabIndex={0}
                  className="h-2 shrink-0 cursor-ns-resize flex items-center justify-center relative focus:outline-none focus-visible:ring-2 focus-visible:ring-[#E8B83A]"
                  style={{ backgroundColor: colors.bgPanelRaised }}
                >
                  {/* Expanded hit zone — 16px total click target (8px visible + 8px above) per HFDS 9.5.1 */}
                  <span aria-hidden="true" className="absolute inset-x-0 -top-2 h-2" />
                  <div className="w-8 h-0.5 rounded-full" style={{ backgroundColor: '#606060' }} />
                </div>
                <div className="flex items-center justify-between px-3 py-1 border-b shrink-0" style={{ borderColor: colors.borderSubtle }}>
                  <span className="text-xs font-bold" style={{ color: colors.value }}>
                    #{selectedPacket.num} {extractCmd(selectedPacket)}
                    {isLive && <span className="ml-2 text-[11px] font-normal" style={{ color: colors.success }}>LIVE</span>}
                  </span>
                  <button onClick={() => setDetailOpen(false)} className="p-0.5 rounded hover:bg-white/5">
                    <X className="size-3" style={{ color: colors.dim }} />
                  </button>
                </div>
                <div className="flex-1 overflow-y-auto">
                  <AnimatePresence mode="wait">
                    <motion.div
                      key={selectedPacket.num}
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.1, ease: 'easeOut' }}
                    >
                      <PacketDetail packet={selectedPacket} showHex={showHex} showWrapper={showWrapper} showFrame={showFrame} />
                    </motion.div>
                  </AnimatePresence>
                </div>
              </div>
            </ContextMenuTrigger>
            <ContextMenuContent>
              <ContextMenuItem icon={ClipboardCopy} onSelect={() => navigator.clipboard.writeText(formatPacketText(selectedPacket))}>
                Copy Full Details
              </ContextMenuItem>
              <ContextMenuItem icon={ClipboardCopy} onSelect={() => navigator.clipboard.writeText(extractCmdArgs(selectedPacket))}>
                Copy Command + Args
              </ContextMenuItem>
              {selectedPacket.raw_hex && (
                <ContextMenuItem icon={Binary} onSelect={() => navigator.clipboard.writeText(selectedPacket.raw_hex)}>
                  Copy Hex
                </ContextMenuItem>
              )}
            </ContextMenuContent>
          </ContextMenuRoot>
        </div>
      )}

    </div>
  )
}
