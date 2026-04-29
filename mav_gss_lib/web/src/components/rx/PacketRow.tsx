import { ChevronRight, ClipboardCopy, Braces, Binary } from 'lucide-react'
import { colors } from '@/lib/colors'
import { col, buildRxRow, composeRxColumns } from '@/lib/columns'
import { CellValue } from '@/components/shared/rendering'
import { packetDisplayLabel, packetPayloadText } from '@/lib/rxPacket'
import {
  ContextMenuRoot,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
} from '@/components/shared/overlays/ContextMenu'
import type { ColumnDef, RxPacket } from '@/lib/types'

interface PacketRowProps {
  packet: RxPacket
  selected: boolean
  showFrame: boolean
  showEcho: boolean
  columns?: ColumnDef[]
  compact?: boolean
  onClick: () => void
}

const FALLBACK_COLUMNS = composeRxColumns([])

export function PacketRow({ packet: p, selected, showFrame, showEcho, columns, compact, onClick }: PacketRowProps) {
  const effectiveSelected = compact ? false : selected
  const handleClick = compact ? () => {} : onClick
  const effectiveColumns = columns && columns.length > 0 ? columns : FALLBACK_COLUMNS
  const row = buildRxRow(p, effectiveColumns)
  return (
    <ContextMenuRoot>
      <ContextMenuTrigger>
        <div
          onClick={handleClick}
          className={`flex items-center text-xs font-mono ${compact ? '' : 'cursor-pointer'} hover:bg-white/[0.03] color-transition`}
          style={{ opacity: p.is_unknown ? 0.5 : 1 }}
        >
          {!compact && (
            <span className={`py-1.5 px-1 ${col.chevron} shrink-0 flex items-center justify-center`}>
              <ChevronRight
                className="size-3 transition-transform duration-200 ease-out"
                style={{
                  color: effectiveSelected ? colors.label : colors.textDisabled,
                  transform: effectiveSelected ? 'rotate(90deg)' : 'rotate(0deg)',
                }}
              />
            </span>
          )}
          {effectiveColumns.map(c => (
            <CellValue key={c.id} col={c} row={row}
              showFrame={showFrame} showEcho={showEcho} />
          ))}
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem icon={ClipboardCopy} onSelect={() => navigator.clipboard.writeText(packetDisplayLabel(p))}>
          Copy Label
        </ContextMenuItem>
        <ContextMenuItem icon={Braces} onSelect={() => navigator.clipboard.writeText(packetPayloadText(p))}>
          Copy Payload
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
