import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical, Shield, ShieldCheck, Trash2, Copy, ArrowUpToLine, ArrowDownToLine } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { colors } from '@/lib/colors'
import { col } from '@/lib/columns'
import {
  ContextMenuRoot, ContextMenuTrigger, ContextMenuContent,
  ContextMenuItem, ContextMenuSeparator,
} from '@/components/shared/ContextMenu'
import type { TxQueueCmd } from '@/lib/types'

interface QueueItemProps {
  item: TxQueueCmd
  index: number
  sortId: string
  expanded: boolean
  isNext: boolean
  isSending: boolean
  isGuarding: boolean
  flash?: boolean
  onSelect: () => void
  onToggleGuard: (index: number) => void
  onDelete: (index: number) => void
  onDuplicate: (index: number) => void
  onMoveToTop: (index: number) => void
  onMoveToBottom: (index: number) => void
}

export function QueueItem({ item, index, sortId, expanded, isNext, isSending, isGuarding, flash, onSelect, onToggleGuard, onDelete, onDuplicate, onMoveToTop, onMoveToBottom }: QueueItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: sortId })

  const display = item.display ?? { title: '?' }
  const displayCmd = display.title ?? '?'
  const displaySubtitle = display.subtitle ?? ''
  const displayArgs = display.fields?.map(f => f.value).join(' ') ?? ''

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  const borderColor = isGuarding ? colors.warning : isSending ? colors.info : item.guard ? colors.warning : colors.borderStrong

  return (
    <ContextMenuRoot>
      <ContextMenuTrigger>
        <div
          ref={setNodeRef}
          style={{ ...style, borderLeftColor: borderColor, backgroundColor: isSending ? `${colors.info}08` : undefined }}
          className={`color-transition rounded-md text-xs border-l-2 mb-0.5 hover:bg-white/[0.03] ${isSending ? 'animate-slide-in' : ''} ${flash ? 'animate-slide-in' : ''}`}
        >
          {/* Main row */}
          <div className="flex items-center gap-1.5 px-1.5 py-1.5 cursor-pointer" onClick={onSelect}>
            <span {...attributes} {...listeners} className="cursor-grab shrink-0 p-0.5 rounded hover:bg-white/[0.06]"
              onClick={(e) => e.stopPropagation()}>
              <GripVertical className="size-3.5" style={{ color: colors.dim }} />
            </span>
            <span className={`${col.num} text-right shrink-0 tabular-nums`} style={{ color: colors.dim }}>{item.num}</span>
            <span className="flex-1 min-w-0 truncate">
              <span className="inline-block px-1.5 py-0 rounded-sm text-[11px] font-semibold" style={{ color: colors.value, backgroundColor: 'rgba(255,255,255,0.06)' }}>{displayCmd}</span>
              {displaySubtitle && <span className="ml-2 text-[11px]" style={{ color: colors.label }}>{displaySubtitle}</span>}
              {displayArgs && <span className="ml-2" style={{ color: colors.dim }}>{displayArgs}</span>}
            </span>
            {isGuarding && (
              <Badge className="text-[11px] px-1.5 py-0 h-5 shrink-0 animate-pulse-warning" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>GUARD</Badge>
            )}
            {isSending && !isGuarding && (
              <Badge className="text-[11px] px-1.5 py-0 h-5 shrink-0 animate-pulse-text" style={{ backgroundColor: `${colors.infoFill}`, color: colors.info }}>SENDING</Badge>
            )}
            {isNext && !isSending && !isGuarding && (
              <Badge className="text-[11px] px-1.5 py-0 h-5 shrink-0" style={{ backgroundColor: `${colors.label}22`, color: colors.label }}>NEXT</Badge>
            )}
            {item.guard && !isSending && !isGuarding && !isNext && (
              <Badge className="text-[11px] px-1.5 py-0 h-5 shrink-0" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>GUARD</Badge>
            )}
            <span className={`${col.size} text-right shrink-0 tabular-nums`} style={{ color: colors.dim }}>{item.size}B</span>
            <div className="flex items-center gap-0.5 shrink-0 ml-1">
              <Button variant="ghost" size="icon" className="size-6 rounded-md btn-feedback"
                onClick={(e) => { e.stopPropagation(); onToggleGuard(index) }}
                title={item.guard ? 'Remove guard' : 'Add guard'}>
                {item.guard
                  ? <ShieldCheck className="size-3.5" style={{ color: colors.warning }} />
                  : <Shield className="size-3.5" style={{ color: colors.dim }} />
                }
              </Button>
              <Button variant="ghost" size="icon" className="size-6 rounded-md btn-feedback"
                onClick={(e) => { e.stopPropagation(); onDelete(index) }} title="Delete">
                <Trash2 className="size-3.5" style={{ color: colors.dim }} />
              </Button>
            </div>
          </div>

          {/* Expanded detail */}
          {expanded && (
            <div className="px-3 pb-2 pt-1 ml-6 space-y-1 animate-slide-in" style={{ borderTop: `1px solid ${colors.borderSubtle}` }}>
              <div className="space-y-0.5">
                {display.fields?.map((f, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span style={{ color: colors.label }}>{f.name}</span>
                    <span style={{ color: colors.sep }}>=</span>
                    <span style={{ color: colors.value }}>{f.value}</span>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span style={{ color: colors.sep }}>Size:</span>
                <span style={{ color: colors.value }}>{item.size}B</span>
              </div>
              {item.guard && <div style={{ color: colors.warning }} className="text-[11px]">Guarded — requires confirmation</div>}
            </div>
          )}
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem icon={item.guard ? Shield : ShieldCheck} onSelect={() => onToggleGuard(index)}>
          {item.guard ? 'Remove Guard' : 'Add Guard'}
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
      </ContextMenuContent>
    </ContextMenuRoot>
  )
}
