import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical, Shield, ShieldCheck, Trash2, Copy, ArrowUpToLine, ArrowDownToLine } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { colors, ptypeColor } from '@/lib/colors'
import { col } from '@/lib/columns'
import { getNodeFullName } from '@/lib/nodes'
import { PtypeBadge } from '@/components/shared/PtypeBadge'
import {
  ContextMenuRoot, ContextMenuTrigger, ContextMenuContent,
  ContextMenuItem, ContextMenuSeparator,
} from '@/components/shared/ContextMenu'
import type { GssConfig, TxQueueCmd, MissionQueueCmd } from '@/lib/types'

interface QueueItemProps {
  item: TxQueueCmd | MissionQueueCmd
  nodeDescriptions?: GssConfig['node_descriptions']
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

const hasEcho = (echo: string) => echo && echo !== 'NONE' && echo !== '0' && echo !== ''

export function QueueItem({ item, nodeDescriptions, index, sortId, expanded, isNext, isSending, isGuarding, flash, onSelect, onToggleGuard, onDelete, onDuplicate, onMoveToTop, onMoveToBottom }: QueueItemProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: sortId })

  const isMission = item.type === 'mission_cmd'
  const mItem = item as MissionQueueCmd
  const cItem = item as TxQueueCmd
  const displayDest = isMission ? (mItem.display?.subtitle ?? '') : cItem.dest
  const displayPtype = isMission ? '' : cItem.ptype
  const displayCmd = isMission ? (mItem.display?.title ?? '?') : cItem.cmd
  const displayArgs = isMission
    ? (mItem.display?.fields?.map(f => f.value).join(' ') ?? '')
    : cItem.args

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  const borderColor = isGuarding ? colors.warning : isSending ? colors.info : (item as TxQueueCmd).guard ? colors.warning : colors.borderStrong

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
            <span className={`${col.node} shrink-0 truncate`}>
              {!isMission && getNodeFullName(displayDest, nodeDescriptions) ? (
                <TooltipProvider delay={300}>
                  <Tooltip>
                    <TooltipTrigger render={<span />} style={{ color: colors.label, cursor: 'default' }}>{displayDest}</TooltipTrigger>
                    <TooltipContent side="top" className="text-xs">{getNodeFullName(displayDest, nodeDescriptions)}</TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              ) : (
                <span style={{ color: colors.label }}>{displayDest}</span>
              )}
            </span>
            <span className={`${col.ptype} shrink-0`}>{displayPtype && <PtypeBadge ptype={displayPtype} />}</span>
            <span className="flex-1 min-w-0 truncate">
              <span className="inline-block px-1.5 py-0 rounded-sm text-[11px] font-semibold" style={{ color: colors.value, backgroundColor: 'rgba(255,255,255,0.06)' }}>{displayCmd}</span>
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
              {isMission ? (
                <div className="space-y-0.5">
                  {mItem.display?.fields?.map((f, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span style={{ color: colors.label }}>{f.name}</span>
                      <span style={{ color: colors.sep }}>=</span>
                      <span style={{ color: colors.value }}>{f.value}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-4">
                    <span className="text-xs"><span style={{ color: colors.sep }}>Src:</span>{' '}
                    {getNodeFullName(cItem.src, nodeDescriptions) ? (
                      <TooltipProvider delay={300}>
                        <Tooltip>
                          <TooltipTrigger render={<span />} style={{ color: colors.label, cursor: 'default' }}>{cItem.src}</TooltipTrigger>
                          <TooltipContent side="top" className="text-xs">{getNodeFullName(cItem.src, nodeDescriptions)}</TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    ) : <span style={{ color: colors.label }}>{cItem.src}</span>}
                  </span>
                  <span className="text-xs"><span style={{ color: colors.sep }}>Dest:</span>{' '}
                    {getNodeFullName(cItem.dest, nodeDescriptions) ? (
                      <TooltipProvider delay={300}>
                        <Tooltip>
                          <TooltipTrigger render={<span />} style={{ color: colors.label, cursor: 'default' }}>{cItem.dest}</TooltipTrigger>
                          <TooltipContent side="top" className="text-xs">{getNodeFullName(cItem.dest, nodeDescriptions)}</TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    ) : <span style={{ color: colors.label }}>{cItem.dest}</span>}
                  </span>
                  {hasEcho(cItem.echo) && (
                    <span className="text-xs"><span style={{ color: colors.sep }}>Echo:</span>{' '}
                      {getNodeFullName(cItem.echo, nodeDescriptions) ? (
                        <TooltipProvider delay={300}>
                          <Tooltip>
                            <TooltipTrigger render={<span />} style={{ color: colors.warning, cursor: 'default' }}>{cItem.echo}</TooltipTrigger>
                            <TooltipContent side="top" className="text-xs">{getNodeFullName(cItem.echo, nodeDescriptions)}</TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      ) : <span style={{ color: colors.warning }}>{cItem.echo}</span>}
                    </span>
                  )}
                  <span className="text-xs"><span style={{ color: colors.sep }}>Type:</span> <span style={{ color: ptypeColor(cItem.ptype) }}>{cItem.ptype}</span></span>
                  <span className="text-xs"><span style={{ color: colors.sep }}>Size:</span> <span style={{ color: colors.value }}>{cItem.size}B</span></span>
                  </div>
                  {(cItem.args_named?.length || cItem.args_extra?.length) ? (
                    <div className="space-y-0.5">
                      {cItem.args_named?.map((a, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          <span style={{ color: colors.label }}>{a.name}</span>
                          <span style={{ color: colors.sep }}>=</span>
                          <span style={{ color: colors.value }}>{a.value}</span>
                        </div>
                      ))}
                      {cItem.args_extra?.map((val, i) => (
                        <div key={`x-${i}`} className="flex items-center gap-2 text-xs">
                          <span style={{ color: colors.dim }}>arg{(cItem.args_named?.length ?? 0) + i}</span>
                          <span style={{ color: colors.sep }}>=</span>
                          <span style={{ color: colors.value }}>{val}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </>
              )}
              {item.guard && <div style={{ color: colors.warning }} className="text-[11px]">Guarded — requires confirmation</div>}
            </div>
          )}
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem icon={item.guard ? Shield : ShieldCheck} onSelect={() => onToggleGuard(index)}>
          {item.guard ? 'Remove Guard' : 'Add Guard'}
        </ContextMenuItem>
        {!isMission && (
          <ContextMenuItem icon={Copy} onSelect={() => onDuplicate(index)}>
            Duplicate
          </ContextMenuItem>
        )}
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
