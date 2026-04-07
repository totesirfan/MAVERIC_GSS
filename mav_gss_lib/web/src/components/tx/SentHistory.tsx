import { useState, useRef, useEffect, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, ChevronRight, History, ClipboardCopy, RotateCcw } from 'lucide-react'
import { colors } from '@/lib/colors'
import { col } from '@/lib/columns'
import { PtypeBadge } from '@/components/shared/PtypeBadge'
import { ContextMenuRoot, ContextMenuTrigger, ContextMenuContent, ContextMenuItem } from '@/components/shared/ContextMenu'
import type { TxHistoryItem, TxColumnDef } from '@/lib/types'

interface SentHistoryProps {
  history: TxHistoryItem[]
  txColumns: TxColumnDef[]
  onRequeue?: (item: TxHistoryItem) => void
}

const springConfig = { type: 'spring' as const, stiffness: 500, damping: 30, mass: 0.8 }

export function SentHistory({ history, txColumns, onRequeue }: SentHistoryProps) {
  const [expanded, setExpanded] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new items arrive
  useEffect(() => {
    if (expanded && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [history.length, expanded])

  const visibleColumns = useMemo(() => {
    return txColumns.filter(col => {
      if (!col.hide_if_all?.length) return true
      const suppressSet = new Set(col.hide_if_all)
      return !history.every(item => {
        return suppressSet.has(String(item.display?.row?.[col.id] ?? ''))
      })
    })
  }, [txColumns, history])

  return (
    <div className="shrink-0 rounded-lg border overflow-hidden shadow-panel" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}>
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-white/[0.03] color-transition"
        style={{ color: colors.dim }}
      >
        {expanded
          ? <ChevronDown className="size-3" style={{ color: colors.label }} />
          : <ChevronRight className="size-3" />
        }
        <History className="size-3" />
        <span>Sent History</span>
        <span className="tabular-nums">({history.length})</span>
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={springConfig}
            className="overflow-hidden border-t"
            style={{ borderColor: colors.borderSubtle }}
          >
            <div ref={scrollRef} className="max-h-40 overflow-y-auto">
              {history.map((item) => {
                const display = item.display ?? { title: '?', row: {}, detail_blocks: [] }
                return (
                  <ContextMenuRoot key={item.n}>
                    <ContextMenuTrigger>
                      <div className="flex items-center gap-2 px-3 py-1.5 text-xs font-mono hover:bg-white/[0.03]">
                        <span className={`${col.num} text-right shrink-0 tabular-nums`} style={{ color: colors.dim }}>{item.n}</span>
                        <span className={`${col.time} shrink-0 tabular-nums`} style={{ color: colors.dim }}>{item.ts}</span>
                        {visibleColumns.length > 0 ? (
                          visibleColumns.map(c => {
                            const val = display.row?.[c.id] ?? ''
                            return (
                              <span key={c.id} className={`${c.width ?? ''} ${c.flex ? 'flex-1 min-w-0 truncate' : 'shrink-0'}`}>
                                {c.badge ? <PtypeBadge ptype={val} /> :
                                 c.id === 'cmd' ? (
                                   <span className="px-2 py-0.5 rounded text-[11px] font-semibold" style={{ color: colors.value, backgroundColor: 'rgba(255,255,255,0.06)' }}>
                                     {String(val)}
                                   </span>
                                 ) : <span style={{ color: colors.dim }}>{val}</span>}
                              </span>
                            )
                          })
                        ) : (
                          <>
                            <span className="shrink-0 px-2 py-0.5 rounded text-[11px] font-semibold" style={{ color: colors.value, backgroundColor: 'rgba(255,255,255,0.06)' }}>
                              {display.title ?? '?'}
                            </span>
                            <span className="flex-1 min-w-0 truncate" style={{ color: colors.dim }} />
                          </>
                        )}
                        <span className={`${col.size} text-right shrink-0 tabular-nums`} style={{ color: colors.dim }}>{item.size}B</span>
                      </div>
                    </ContextMenuTrigger>
                    <ContextMenuContent>
                      <ContextMenuItem icon={ClipboardCopy} onSelect={() => {
                        const text = String(display.row?.cmd ?? display.title ?? '?')
                        navigator.clipboard.writeText(text)
                      }}>
                        Copy Command
                      </ContextMenuItem>
                      {onRequeue && (
                        <ContextMenuItem icon={RotateCcw} onSelect={() => onRequeue(item)}>
                          Re-queue
                        </ContextMenuItem>
                      )}
                    </ContextMenuContent>
                  </ContextMenuRoot>
                )
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
