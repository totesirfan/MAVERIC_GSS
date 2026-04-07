import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { X, Search, Clock, ChevronDown, ChevronRight, AlertTriangle, Binary, ArrowDownToLine, ArrowUpFromLine, Play, ClipboardCopy, Braces } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { Separator } from '@/components/ui/separator'
import { colors, frameColor } from '@/lib/colors'
import { col } from '@/lib/columns'
import { ContextMenuRoot, ContextMenuTrigger, ContextMenuContent, ContextMenuItem, ContextMenuSeparator } from '@/components/shared/ContextMenu'
import { CellValue, SemanticBlocks, ProtocolBlocks, IntegritySection, extractFromRendering } from '@/components/shared/RenderingBlocks'
import type { ColumnDef, RenderingData } from '@/lib/types'

type LogEntry = Record<string, unknown>

interface LogViewerProps {
  open: boolean
  onClose: () => void
  onStartReplay?: (sessionId: string) => void
}

/** Parse session ID like "downlink_20260404_142638" into a readable date/time */
function parseSessionLabel(sid: string): { date: string; time: string; label: string } {
  const m = sid.match(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/)
  if (m) {
    const date = `${m[1]}-${m[2]}-${m[3]}`
    const time = `${m[4]}:${m[5]}:${m[6]}`
    const prefix = sid.split('_')[0] ?? ''
    return { date, time, label: prefix }
  }
  return { date: '', time: '', label: sid }
}

const springConfig = { type: 'spring' as const, stiffness: 500, damping: 30, mass: 0.8 }
let hasLoadedLogViewer = false


export function LogViewer({ open, onClose, onStartReplay }: LogViewerProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<Element | null>(null)
  const [sessions, setSessions] = useState<Record<string, unknown>[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [expandedSet, setExpandedSet] = useState<Set<number>>(new Set())
  const [cmdFilter, setCmdFilter] = useState('')
  const [fromTime, setFromTime] = useState('')
  const [toTime, setToTime] = useState('')
  const [loading, setLoading] = useState(false)
  const [dateFilter, setDateFilter] = useState('')
  const animateOnMount = hasLoadedLogViewer
  const [columns, setColumns] = useState<ColumnDef[]>([])

  useEffect(() => {
    hasLoadedLogViewer = true
  }, [])

  useEffect(() => {
    if (!open) return
    fetch('/api/columns')
      .then((r) => r.json())
      .then((data: ColumnDef[]) => setColumns(data))
      .catch(() => {})
  }, [open])

  // Save / restore focus
  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement
    } else if (triggerRef.current && triggerRef.current instanceof HTMLElement) {
      triggerRef.current.focus()
      triggerRef.current = null
    }
  }, [open])

  // Focus trap
  const handleTab = useCallback((e: KeyboardEvent) => {
    if (e.key !== 'Tab' || !panelRef.current) return
    const focusable = panelRef.current.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey) {
      if (document.activeElement === first) { e.preventDefault(); last.focus() }
    } else {
      if (document.activeElement === last) { e.preventDefault(); first.focus() }
    }
  }, [])

  useEffect(() => {
    if (!open) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onClose() }
      if (e.key === 'Tab') handleTab(e)
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, onClose, handleTab])

  // Auto-focus panel on open
  useEffect(() => {
    if (open && panelRef.current) {
      const btn = panelRef.current.querySelector<HTMLElement>('button')
      btn?.focus()
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    fetch('/api/logs')
      .then((r) => r.json())
      .then((data: Record<string, unknown>[]) => setSessions(data))
      .catch(() => {})
  }, [open])

  const fetchEntries = useCallback((sessionId: string) => {
    setLoading(true)
    setExpandedSet(new Set())
    const params = new URLSearchParams()
    if (cmdFilter) params.set('cmd', cmdFilter)
    if (fromTime) params.set('from', fromTime)
    if (toTime) params.set('to', toTime)
    const qs = params.toString()
    fetch(`/api/logs/${sessionId}${qs ? `?${qs}` : ''}`)
      .then((r) => r.json())
      .then((data: LogEntry[]) => { setEntries(data); setLoading(false) })
      .catch(() => { setEntries([]); setLoading(false) })
  }, [cmdFilter, fromTime, toTime])

  useEffect(() => {
    if (selected) fetchEntries(selected)
  }, [selected, fetchEntries])

  useEffect(() => {
    if (!open) { setSelected(null); setEntries([]); setCmdFilter(''); setFromTime(''); setToTime(''); setExpandedSet(new Set()); setDateFilter('') }
  }, [open])

  // Derive whether selected session is downlink
  const isDownlinkSession = selected?.startsWith('downlink') ?? false

  // Compute session counts per date for calendar markers
  const sessionDateCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const s of sessions) {
      const sid = (s.session_id ?? s.id ?? s.filename) as string
      const mtime = s.mtime as number | undefined
      let ds = ''
      if (mtime) {
        ds = new Date(mtime * 1000).toLocaleDateString('en-CA')
      } else {
        ds = parseSessionLabel(sid).date
      }
      if (ds) counts[ds] = (counts[ds] || 0) + 1
    }
    return counts
  }, [sessions])

  // Dates that have sessions — for calendar highlighting
  const sessionDates = useMemo(() => {
    return Object.keys(sessionDateCounts).map(d => new Date(d + 'T00:00:00'))
  }, [sessionDateCounts])

  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex"
          initial={animateOnMount ? { opacity: 0 } : false}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          {/* Frosted backdrop */}
          <motion.div
            className="absolute inset-0 frosted-backdrop"
            style={{ backgroundColor: 'rgba(0,0,0,0.7)' }}
          />

          {/* Panel */}
          <motion.div
            ref={panelRef}
            className="flex flex-1 m-4 rounded-lg border overflow-hidden shadow-overlay relative"
            style={{ backgroundColor: colors.bgPanelRaised, borderColor: colors.borderStrong }}
            initial={animateOnMount ? { opacity: 0, scale: 0.95 } : false}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={springConfig}
          >

            {/* Left sidebar: calendar + session list */}
            <div className="w-72 shrink-0 border-r flex flex-col overflow-hidden" style={{ borderColor: colors.borderSubtle }}>
              <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: colors.borderSubtle }}>
                <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.label }}>Sessions</span>
                <div className="flex items-center gap-1">
                  {dateFilter && (
                    <button onClick={() => setDateFilter('')} className="text-[11px] px-1.5 py-0.5 rounded hover:bg-white/5" style={{ color: colors.dim }}>
                      Clear
                    </button>
                  )}
                  <button onClick={onClose} className="p-1 rounded hover:bg-white/5">
                    <X className="size-3.5" style={{ color: colors.dim }} />
                  </button>
                </div>
              </div>
              {/* Calendar */}
              <div className="shrink-0 border-b flex justify-center" style={{ borderColor: colors.borderSubtle }}>
                <Calendar
                  mode="single"
                  selected={dateFilter ? new Date(dateFilter + 'T00:00:00') : undefined}
                  onSelect={(day) => setDateFilter(day ? day.toLocaleDateString('en-CA') : '')}
                  modifiers={{ hasSession: sessionDates }}
                  modifiersClassNames={{ hasSession: 'log-day-marker' }}
                  className="!p-2 !bg-transparent w-full [--cell-size:--spacing(6)]"
                />
              </div>
              {/* Session list */}
              <div className="flex-1 overflow-y-auto">
                {sessions.length === 0 ? (
                  <div className="px-3 py-4 text-xs text-center" style={{ color: colors.dim }}>No sessions found</div>
                ) : (
                  sessions.filter((s) => {
                    if (!dateFilter) return true
                    const sid = (s.session_id ?? s.id ?? s.filename) as string
                    const mtime = s.mtime as number | undefined
                    let ds = ''
                    if (mtime) {
                      ds = new Date(mtime * 1000).toLocaleDateString('en-CA')
                    } else {
                      ds = parseSessionLabel(sid).date
                    }
                    return ds === dateFilter
                  }).map((s) => {
                    const sid = (s.session_id ?? s.id ?? s.filename) as string
                    const mtime = s.mtime as number | undefined
                    const direction = String(s.direction ?? (sid.startsWith('uplink') ? 'uplink' : 'downlink'))
                    const isDownlink = direction === 'downlink'
                    let dateStr = '', timeStr2 = ''
                    if (mtime) {
                      const d = new Date(mtime * 1000)
                      dateStr = d.toLocaleDateString('en-CA')
                      timeStr2 = d.toLocaleTimeString('en-GB', { hour12: false })
                    } else {
                      const p = parseSessionLabel(sid)
                      dateStr = p.date; timeStr2 = p.time
                    }
                    const sizeKb = typeof s.size === 'number' ? (s.size / 1024).toFixed(1) + ' KB' : '?'
                    const isSel = selected === sid
                    const dirColor = isDownlink ? colors.success : colors.label
                    const DirIcon = isDownlink ? ArrowDownToLine : ArrowUpFromLine
                    const tagMatch = sid.match(/\d{8}_\d{6}_(.+?)(?:\.jsonl)?$/)
                    const tag = tagMatch ? tagMatch[1] : ''
                    const sessionName = sid.replace(/\.jsonl$/, '')
                    return (
                      <div
                        key={sid}
                        className="flex items-center border-b transition-colors hover:bg-white/5"
                        style={{ borderColor: colors.borderSubtle, backgroundColor: isSel ? `${colors.label}11` : 'transparent', borderLeft: `2px solid ${isSel ? dirColor : 'transparent'}` }}
                      >
                        <button
                          onClick={() => setSelected(sid)}
                          className="flex-1 text-left px-2 py-1.5 min-w-0"
                        >
                          <div className="flex items-center gap-1.5">
                            <DirIcon className="size-3 shrink-0" style={{ color: dirColor }} />
                            <span className="text-[11px] font-bold uppercase shrink-0" style={{ color: dirColor }}>
                              {isDownlink ? 'RX' : 'TX'}
                            </span>
                            <span className="text-[11px] font-mono tabular-nums" style={{ color: isSel ? colors.label : colors.value }}>
                              {dateStr} {timeStr2}
                            </span>
                            <span className="text-[11px]" style={{ color: colors.dim }}>{sizeKb}</span>
                          </div>
                          {tag && <div className="text-[11px] truncate pl-5" style={{ color: colors.sep }}>{tag}</div>}
                          <div className="text-[11px] font-mono truncate pl-5" style={{ color: colors.sep }}>{sessionName}</div>
                        </button>
                        {isDownlink && onStartReplay && (
                          <Button
                            variant="ghost" size="icon"
                            className="size-6 shrink-0 mr-1 btn-feedback"
                            onClick={(e) => { e.stopPropagation(); onStartReplay(sid); onClose() }}
                            title="Replay session"
                          >
                            <Play className="size-3" style={{ color: colors.warning }} />
                          </Button>
                        )}
                      </div>
                    )
                  })
                )}
              </div>
            </div>

            {/* Right area */}
            <div className="flex-1 flex flex-col overflow-hidden">
              {/* Search bar */}
              <div className="flex items-center gap-2 px-3 py-2 border-b" style={{ borderColor: colors.borderSubtle }}>
                <Search className="size-3.5 shrink-0" style={{ color: colors.dim }} />
                <input placeholder="Command..." className="flex-1 px-2 py-1 rounded text-xs outline-none border border-[#222222] focus:border-[#30C8E0] focus:ring-1 focus:ring-[#30C8E0]/20"
                  style={{ backgroundColor: colors.bgApp, color: colors.value }} value={cmdFilter} onChange={(e) => setCmdFilter(e.target.value)} />
                <input placeholder="From HH:MM" className="w-24 px-2 py-1 rounded text-xs outline-none border border-[#222222] focus:border-[#30C8E0] focus:ring-1 focus:ring-[#30C8E0]/20"
                  style={{ backgroundColor: colors.bgApp, color: colors.value }} value={fromTime} onChange={(e) => setFromTime(e.target.value)} />
                <input placeholder="To HH:MM" className="w-24 px-2 py-1 rounded text-xs outline-none border border-[#222222] focus:border-[#30C8E0] focus:ring-1 focus:ring-[#30C8E0]/20"
                  style={{ backgroundColor: colors.bgApp, color: colors.value }} value={toTime} onChange={(e) => setToTime(e.target.value)} />
                {selected && <span className="text-[11px] shrink-0" style={{ color: colors.dim }}>{entries.length} entries</span>}
              </div>

              {/* Column headers */}
              {selected && entries.length > 0 && columns.length > 0 && (
                <div className="flex items-center text-[11px] font-light px-2 py-0.5 shrink-0" style={{ color: colors.sep }}>
                  <span className="w-5 px-1" />
                  {columns.map(c => (
                    <span
                      key={c.id}
                      className={`px-2 shrink-0 ${c.flex ? 'flex-1' : ''} ${c.align === 'right' ? 'text-right' : ''} ${c.width ?? ''}`}
                    >
                      {c.label}
                    </span>
                  ))}
                </div>
              )}

              {/* Entries */}
              <div className="flex-1 overflow-y-auto">
                {!selected ? (
                  <div className="flex items-center justify-center h-full text-xs" style={{ color: colors.dim }}>Select a session</div>
                ) : loading ? (
                  <div className="flex items-center justify-center h-full text-xs" style={{ color: colors.dim }}>Loading...</div>
                ) : entries.length === 0 ? (
                  <div className="flex items-center justify-center h-full text-xs" style={{ color: colors.dim }}>No matching entries</div>
                ) : (
                  entries.map((e, i) => {
                    const num = (e.num ?? i + 1) as number
                    const timeStr = String(e.time ?? '')
                    const frame = String(e.frame ?? '')
                    const size = (e.size ?? 0) as number
                    const isEcho = e.is_echo as boolean
                    const isDup = e.is_dup as boolean
                    const rawHex = String(e.raw_hex ?? '')
                    const warnings = (Array.isArray(e.warnings) ? e.warnings : []) as string[]
                    const isExpanded = expandedSet.has(i)
                    const rendering = e._rendering as RenderingData | undefined
                    const row = rendering?.row

                    return (
                      <ContextMenuRoot key={i}>
                        <ContextMenuTrigger>
                          <div>
                            {/* Row */}
                            <div
                              className="flex items-center px-3 py-1 text-xs font-mono cursor-pointer hover:bg-white/[0.03]"
                              style={{
                                backgroundColor: isExpanded ? `${colors.label}08` : undefined,
                                opacity: row?._meta?.opacity ?? 1,
                              }}
                              onClick={() => setExpandedSet(prev => { const next = new Set(prev); if (next.has(i)) next.delete(i); else next.add(i); return next })}
                            >
                              {isExpanded ? <ChevronDown className="size-3 shrink-0" style={{ color: colors.label }} /> : <ChevronRight className="size-3 shrink-0" style={{ color: colors.dim }} />}
                              {row && columns.length > 0 ? (
                                columns.map(c => (
                                  <CellValue key={c.id} col={c} row={row} showFrame={true} showEcho={true} />
                                ))
                              ) : (
                                <>
                                  <span className={`${col.num} text-right shrink-0 tabular-nums`} style={{ color: colors.dim }}>{num}</span>
                                  <span className={`${col.time} shrink-0 tabular-nums`} style={{ color: colors.dim }}>{timeStr}</span>
                                  <span className={`${col.frame} shrink-0`} style={{ color: frameColor(frame) }}>{frame || '--'}</span>
                                  <span className="flex-1 min-w-0 truncate" style={{ color: colors.dim }}>{size}B</span>
                                  <span className={`${col.flags} flex items-center gap-1 justify-end shrink-0`}>
                                    {isEcho && <Badge className="text-[11px] px-1 py-0 h-5" style={{ backgroundColor: `${colors.ulColor}22`, color: colors.ulColor }}>UL</Badge>}
                                    {isDup && <Badge className="text-[11px] px-1 py-0 h-5" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>DUP</Badge>}
                                  </span>
                                </>
                              )}
                            </div>

                            {/* Expanded detail */}
                            {isExpanded && (
                              <div className="px-6 py-2 space-y-1.5" style={{ backgroundColor: colors.bgApp }}>
                                {rendering ? (
                                  <>
                                    <SemanticBlocks blocks={rendering.detail_blocks} />

                                    {warnings.length > 0 && (
                                      <div className="flex items-center gap-1">
                                        <AlertTriangle className="size-3" style={{ color: colors.warning }} />
                                        {warnings.map((w, wi) => (
                                          <Badge key={wi} className="text-[11px] h-5" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>{w}</Badge>
                                        ))}
                                      </div>
                                    )}

                                    {rendering.integrity_blocks.length > 0 && (
                                      <>
                                        <Separator style={{ backgroundColor: colors.borderSubtle }} />
                                        <IntegritySection blocks={rendering.integrity_blocks} />
                                      </>
                                    )}

                                    {rendering.protocol_blocks.length > 0 && (
                                      <>
                                        <Separator style={{ backgroundColor: colors.borderSubtle }} />
                                        <ProtocolBlocks blocks={rendering.protocol_blocks} />
                                      </>
                                    )}
                                  </>
                                ) : (
                                  <div className="flex items-center gap-1 text-xs">
                                    <Clock className="size-3" style={{ color: colors.sep }} />
                                    <span style={{ color: colors.sep }}>Time:</span>
                                    <span style={{ color: colors.value }}>{timeStr}</span>
                                  </div>
                                )}

                                {rawHex && (
                                  <>
                                    <Separator style={{ backgroundColor: colors.borderSubtle }} />
                                    <div className="flex items-start gap-1">
                                      <Binary className="size-3 mt-0.5 shrink-0" style={{ color: colors.sep }} />
                                      <pre className="text-[11px] p-2 rounded font-mono flex-1 whitespace-pre-wrap break-all" style={{ color: colors.dim, backgroundColor: 'rgba(0,0,0,0.3)' }}>
                                        {rawHex.match(/.{1,2}/g)?.join(' ')}
                                      </pre>
                                    </div>
                                  </>
                                )}
                              </div>
                            )}
                          </div>
                        </ContextMenuTrigger>
                        <ContextMenuContent>
                          <ContextMenuItem
                            icon={ClipboardCopy}
                            onSelect={() => navigator.clipboard.writeText(extractFromRendering(rendering).cmd)}
                          >
                            Copy Command
                          </ContextMenuItem>
                          <ContextMenuItem
                            icon={Braces}
                            onSelect={() => navigator.clipboard.writeText(extractFromRendering(rendering).args)}
                          >
                            Copy Args
                          </ContextMenuItem>
                          {rawHex && (
                            <ContextMenuItem
                              icon={Binary}
                              onSelect={() => navigator.clipboard.writeText(rawHex)}
                            >
                              Copy Hex
                            </ContextMenuItem>
                          )}
                          {isDownlinkSession && onStartReplay && (
                            <>
                              <ContextMenuSeparator />
                              <ContextMenuItem
                                icon={Play}
                                onSelect={() => { onStartReplay(selected!); onClose() }}
                              >
                                Replay from Here
                              </ContextMenuItem>
                            </>
                          )}
                        </ContextMenuContent>
                      </ContextMenuRoot>
                    )
                  })
                )}
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
