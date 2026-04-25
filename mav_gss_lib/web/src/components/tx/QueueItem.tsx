import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  GripVertical, Shield, ShieldCheck, Trash2, Copy, ArrowUpToLine,
  ArrowDownToLine, RotateCcw,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { colors } from '@/lib/colors'
import { col } from '@/lib/columns'
import { cellText } from '@/lib/rendering'
import { ValueBadge } from '@/components/shared/ValueBadge'
import {
  ContextMenuRoot, ContextMenuTrigger, ContextMenuContent,
  ContextMenuItem, ContextMenuSeparator,
} from '@/components/shared/ContextMenu'
import { useTx } from '@/state/tx'
import { VerifierTickStrip } from './VerifierTickStrip'
import { VerifierDetailBlock } from './VerifierDetailBlock'
import type { TxQueueCmd, TxHistoryItem, TxColumnDef, TxRowStatus } from '@/lib/types'

const TERMINAL: TxRowStatus[] = ['complete', 'failed', 'timed_out']
const isTerminal = (s: TxRowStatus) => TERMINAL.includes(s)

function railColor(status: TxRowStatus, guard: boolean, isGuarding: boolean): string {
  if (isGuarding) return colors.warning
  if (status === 'sending') return colors.info
  if (status === 'released') return colors.warning
  if (status === 'accepted') return colors.success
  if (status === 'complete') return colors.success
  if (status === 'failed') return colors.danger
  if (status === 'timed_out') return colors.dim
  return guard ? colors.warning : colors.borderStrong
}

interface QueueItemProps {
  item: TxQueueCmd | TxHistoryItem
  status: TxRowStatus
  index: number            // queue index (pending) or 0 placeholder (terminal)
  sortId: string
  expanded: boolean
  isGuarding: boolean
  flash?: boolean
  compact?: boolean
  visibleColumns: TxColumnDef[]
  onSelect: () => void
  onToggleGuard: (index: number) => void
  onDelete: (index: number) => void
  onDuplicate: (index: number) => void
  onMoveToTop: (index: number) => void
  onMoveToBottom: (index: number) => void
  onRequeue?: (item: TxHistoryItem) => void
}

export function QueueItem({
  item, status, index, sortId, expanded, isGuarding, flash, compact,
  visibleColumns, onSelect, onToggleGuard, onDelete, onDuplicate,
  onMoveToTop, onMoveToBottom, onRequeue,
}: QueueItemProps) {
  const pending = status === 'pending' || status === 'sending'

  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id: sortId, disabled: !pending })

  const display = item.display ?? { title: '?', row: {}, detail_blocks: [] }
  const num = 'num' in item ? item.num : ('n' in item ? item.n : 0)
  const guard = 'guard' in item ? item.guard : false
  const size = item.size

  // Join this row to a live verifier instance, if any. Backend stamps
  // `event_id` on history rows via `_record_sent`; queue items have no
  // event_id until sent, so `instance` is null for pending rows.
  const { verification } = useTx()
  const cmdEventId = (item as { event_id?: string }).event_id ?? ''
  const instance = cmdEventId ? (verification.get(cmdEventId) ?? null) : null

  // For sent rows, the incoming `status` is hardcoded to 'complete' upstream.
  // Override from the live verifier instance stage so the left rail reflects
  // the actual verification outcome (green=complete, red=failed, gray=timed_out,
  // pulsing yellow=released-waiting). Pending/sending rows keep their prop status.
  const effectiveStatus: TxRowStatus = (() => {
    if (status === 'pending' || status === 'sending') return status
    if (!instance) return status
    if (instance.stage === 'received') return 'accepted'
    return instance.stage as TxRowStatus
  })()
  const effectiveTerminal = isTerminal(effectiveStatus)

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : (effectiveTerminal ? 0.6 : 1),
  }

  const borderColor = railColor(effectiveStatus, guard, isGuarding)
  const pulseClass =
    effectiveStatus === 'sending' ? 'animate-slide-in' :
    effectiveStatus === 'released' ? 'animate-pulse-warning' : ''

  return (
    <ContextMenuRoot>
      <ContextMenuTrigger>
        <div
          ref={setNodeRef}
          data-follow-id={sortId}
          style={{
            ...style,
            ...(compact ? {} : { borderLeftColor: borderColor }),
            backgroundColor: status === 'sending' ? `${colors.info}08` : undefined,
          }}
          className={`color-transition rounded-md text-xs ${compact ? '' : 'border-l-2'} mb-0.5 hover:bg-white/[0.03] ${pulseClass} ${flash ? 'animate-slide-in' : ''}`}
        >
          <div className="flex items-center gap-1.5 px-1.5 py-1.5 cursor-pointer" onClick={onSelect}>
            {!compact && (
              pending ? (
                <span {...attributes} {...listeners}
                  className={`${col.grip} cursor-grab shrink-0 p-0.5 rounded hover:bg-white/[0.06] flex items-center justify-center`}
                  onClick={(e) => e.stopPropagation()}
                >
                  <GripVertical className="size-3.5" style={{ color: colors.dim }} />
                </span>
              ) : (
                <span className={`${col.grip} shrink-0`} aria-hidden="true" />
              )
            )}
            <span className={`${col.num} text-right shrink-0 tabular-nums`} style={{ color: colors.dim }}>{num}</span>
            {visibleColumns.length > 0 ? (
              visibleColumns.map(c => {
                if (c.id === 'verifiers') {
                  return (
                    <span key={c.id} className={`${c.width ?? ''} ${c.flex ? 'flex-1 min-w-0 truncate' : 'shrink-0'} text-right`}>
                      <VerifierTickStrip instance={instance} now_ms={Date.now()} />
                    </span>
                  )
                }
                const cell = display.row?.[c.id]
                const val = cellText(cell)
                return (
                  <span key={c.id} className={`${c.width ?? ''} ${c.flex ? 'flex-1 min-w-0 truncate' : 'shrink-0'}`}>
                    {cell?.badge ? <ValueBadge value={val} tone={cell.tone} /> :
                     c.id === 'cmd' ? (
                       <>
                         <span className="inline-block px-1.5 py-0 rounded-sm text-[11px] font-semibold" style={{ color: colors.value, backgroundColor: 'rgba(255,255,255,0.06)' }}>
                           {String(val).split(' ')[0]}
                         </span>
                         {String(val).includes(' ') && <span className="ml-2" style={{ color: colors.dim }}>{String(val).split(' ').slice(1).join(' ')}</span>}
                       </>
                     ) : <span style={{ color: colors.label }}>{val}</span>}
                  </span>
                )
              })
            ) : (
              <span className="flex-1 min-w-0 truncate">
                <span className="inline-block px-1.5 py-0 rounded-sm text-[11px] font-semibold" style={{ color: colors.value, backgroundColor: 'rgba(255,255,255,0.06)' }}>{display.title ?? '?'}</span>
              </span>
            )}
            {!compact && isGuarding && (
              <Badge className="text-[11px] px-1.5 py-0 h-5 shrink-0 animate-pulse-warning" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>GUARD</Badge>
            )}
            {!compact && status === 'sending' && !isGuarding && (
              <Badge className="text-[11px] px-1.5 py-0 h-5 shrink-0 animate-pulse-text" style={{ backgroundColor: `${colors.infoFill}`, color: colors.info }}>SENDING</Badge>
            )}
            {!compact && status === 'pending' && index === 0 && !isGuarding && (
              <Badge className="text-[11px] px-1.5 py-0 h-5 shrink-0" style={{ backgroundColor: `${colors.label}22`, color: colors.label }}>NEXT</Badge>
            )}
            {!compact && status === 'pending' && guard && index !== 0 && (
              <Badge className="text-[11px] px-1.5 py-0 h-5 shrink-0" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>GUARD</Badge>
            )}
            {!compact && (
              <span className={`${col.size} text-right shrink-0 tabular-nums`} style={{ color: colors.dim }}>{size}B</span>
            )}
            {!compact && (
              pending ? (
                <div className={`${col.actions} flex items-center gap-0.5 shrink-0 ml-1 justify-end`}>
                  <Button variant="ghost" size="icon" className="size-6 rounded-md btn-feedback"
                    onClick={(e) => { e.stopPropagation(); onToggleGuard(index) }}
                    title={guard ? 'Remove guard' : 'Add guard'}>
                    {guard
                      ? <ShieldCheck className="size-3.5" style={{ color: colors.warning }} />
                      : <Shield className="size-3.5" style={{ color: colors.dim }} />
                    }
                  </Button>
                  <Button variant="ghost" size="icon" className="size-6 rounded-md btn-feedback"
                    onClick={(e) => { e.stopPropagation(); onDelete(index) }} title="Delete">
                    <Trash2 className="size-3.5" style={{ color: colors.dim }} />
                  </Button>
                </div>
              ) : (
                <span className={`${col.actions} shrink-0 ml-1`} aria-hidden="true" />
              )
            )}
          </div>

          {expanded && (
            <div className="px-3 pb-2 pt-1 ml-6 space-y-2 animate-slide-in" style={{ borderTop: `1px solid ${colors.borderSubtle}` }}>
              {display.detail_blocks?.map((block, i) => (
                <div key={i} className="space-y-0.5">
                  <div className="text-[11px] font-bold uppercase tracking-wide" style={{ color: colors.dim }}>{block.label}</div>
                  {block.fields.map((f, j) => (
                    <div key={j} className="flex items-center gap-2 text-xs">
                      <span style={{ color: colors.label }}>{f.name}</span>
                      <span style={{ color: colors.sep }}>=</span>
                      <span style={{ color: colors.value }}>{f.value}</span>
                    </div>
                  ))}
                </div>
              ))}
              <div className="flex items-center gap-2 text-xs">
                <span style={{ color: colors.sep }}>Size:</span>
                <span style={{ color: colors.value }}>{size}B</span>
              </div>
              {pending && guard && <div style={{ color: colors.warning }} className="text-[11px]">Guarded — requires confirmation</div>}
              {instance && <VerifierDetailBlock instance={instance} now_ms={Date.now()} />}
            </div>
          )}
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        {pending ? (
          <>
            <ContextMenuItem icon={guard ? Shield : ShieldCheck} onSelect={() => onToggleGuard(index)}>
              {guard ? 'Remove Guard' : 'Add Guard'}
            </ContextMenuItem>
            <ContextMenuItem icon={Copy} onSelect={() => onDuplicate(index)}>
              Duplicate
            </ContextMenuItem>
            <ContextMenuItem icon={ArrowUpToLine} onSelect={() => onMoveToTop(index)}>
              Move to Top
            </ContextMenuItem>
            <ContextMenuItem icon={ArrowDownToLine} onSelect={() => onMoveToBottom(index)}>
              Move to Bottom
            </ContextMenuItem>
            <ContextMenuSeparator />
            <ContextMenuItem icon={Trash2} onSelect={() => onDelete(index)} destructive>
              Delete
            </ContextMenuItem>
          </>
        ) : (
          <>
            <ContextMenuItem icon={Copy} onSelect={() => {
              const text = cellText(display.row?.cmd) || String(display.title ?? '?')
              navigator.clipboard.writeText(text)
            }}>
              Copy Command
            </ContextMenuItem>
            {onRequeue && 'payload' in item && (
              <ContextMenuItem icon={RotateCcw} onSelect={() => onRequeue(item as TxHistoryItem)}>
                Re-queue
              </ContextMenuItem>
            )}
          </>
        )}
      </ContextMenuContent>
    </ContextMenuRoot>
  )
}
