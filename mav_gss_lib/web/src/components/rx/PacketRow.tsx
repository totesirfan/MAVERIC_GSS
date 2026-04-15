import { Badge } from '@/components/ui/badge'
import { ChevronRight, ClipboardCopy, Braces, Binary } from 'lucide-react'
import { colors } from '@/lib/colors'
import { col } from '@/lib/columns'
import { CellValue, extractFromRendering } from '@/components/shared/RenderingBlocks'
import {
  ContextMenuRoot,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
} from '@/components/shared/ContextMenu'
import type { ColumnDef, GssConfig, RxPacket } from '@/lib/types'

interface PacketRowProps {
  packet: RxPacket
  nodeDescriptions?: GssConfig['node_descriptions']
  selected: boolean
  showFrame: boolean
  showEcho: boolean
  columns?: ColumnDef[]
  compact?: boolean
  onClick: () => void
}

export function PacketRow({ packet: p, nodeDescriptions, selected, showFrame, showEcho, columns, compact, onClick }: PacketRowProps) {
  const effectiveSelected = compact ? false : selected
  const handleClick = compact ? () => {} : onClick
  return (
    <ContextMenuRoot>
      <ContextMenuTrigger>
        <div
          onClick={handleClick}
          className={`flex items-center text-xs font-mono ${compact ? '' : 'cursor-pointer'} hover:bg-white/[0.03] color-transition`}
          style={{
            opacity: p._rendering?.row?._meta?.opacity
              ?? (p.is_unknown ? 0.5 : 1),
          }}
        >
          {/* Expand indicator */}
          {!compact && (
            <span className={`py-1.5 px-1 ${col.chevron} shrink-0 flex items-center justify-center`}>
              <ChevronRight
                className="size-3 transition-transform duration-200 ease-out"
                style={{ color: effectiveSelected ? colors.label : colors.textDisabled, transform: effectiveSelected ? 'rotate(90deg)' : 'rotate(0deg)' }}
              />
            </span>
          )}
          {(columns ?? []).length > 0 && p._rendering?.row ? (
            <>
              {columns!.map(c => (
                <CellValue key={c.id} col={c} row={p._rendering!.row}
                  showFrame={showFrame} showEcho={showEcho} nodeDescriptions={nodeDescriptions} />
              ))}
            </>
          ) : (
            <>
              <span className={`py-1.5 px-2 ${col.num} shrink-0 text-right tabular-nums`} style={{ color: effectiveSelected ? colors.label : colors.dim }}>{p.num}</span>
              <span className={`py-1.5 px-2 ${col.time} shrink-0 tabular-nums whitespace-nowrap`} style={{ color: colors.dim }}>{p.time}</span>
              <span className="py-1.5 px-2 flex-1 min-w-0 truncate" style={{ color: colors.dim }}>{p.size}B</span>
              <span className={`py-1.5 px-2 ${col.flags} shrink-0`}>
                <span className="flex items-center gap-1 justify-end whitespace-nowrap">
                  {p.is_echo && <Badge className="text-[11px] px-1 py-0 h-5" style={{ backgroundColor: `${colors.ulColor}22`, color: colors.ulColor }}>UL</Badge>}
                  {p.is_dup && <Badge className="text-[11px] px-1 py-0 h-5" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>DUP</Badge>}
                  {p.is_unknown && <Badge className="text-[11px] px-1 py-0 h-5" style={{ backgroundColor: `${colors.error}22`, color: colors.error }}>UNK</Badge>}
                </span>
              </span>
            </>
          )}
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem icon={ClipboardCopy} onSelect={() => navigator.clipboard.writeText(extractFromRendering(p._rendering).cmd)}>
          Copy Command
        </ContextMenuItem>
        <ContextMenuItem icon={Braces} onSelect={() => navigator.clipboard.writeText(extractFromRendering(p._rendering).args)}>
          Copy Args
        </ContextMenuItem>
        {p.raw_hex && (
          <ContextMenuItem icon={Binary} onSelect={() => navigator.clipboard.writeText(p.raw_hex)}>
            Copy Hex
          </ContextMenuItem>
        )}
      </ContextMenuContent>
    </ContextMenuRoot>
  )
}
