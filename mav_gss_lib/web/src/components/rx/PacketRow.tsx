import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { ChevronRight, ClipboardCopy, Braces, Binary } from 'lucide-react'
import { colors, frameColor } from '@/lib/colors'
import { col } from '@/lib/columns'
import { nodeFullName } from '@/lib/nodes'
import { PtypeBadge } from '@/components/shared/PtypeBadge'
import {
  ContextMenuRoot,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
} from '@/components/shared/ContextMenu'
import type { RxPacket } from '@/lib/types'

interface PacketRowProps {
  packet: RxPacket
  selected: boolean
  showFrame: boolean
  showEcho: boolean
  onClick: () => void
}

function NodeName({ name, color }: { name: string; color: string }) {
  const full = nodeFullName[name]
  if (!full) return <span style={{ color }}>{name}</span>
  return (
    <TooltipProvider delay={300}>
      <Tooltip>
        <TooltipTrigger render={<span />} style={{ color, cursor: 'help' }}>{name}</TooltipTrigger>
        <TooltipContent side="top" className="text-xs">
          {full}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

function importantArgs(p: RxPacket): string {
  const named = p.args_named ?? []
  const important = named.filter(a => a.important)
  const show = important.length > 0 ? important : named
  const parts = show.map(a => a.value)
  if (p.args_extra?.length && !important.length) parts.push(...p.args_extra)
  return parts.join(' ')
}

function allArgs(p: RxPacket): string {
  const named = (p.args_named ?? []).map(a => `${a.name}=${a.value}`)
  const extra = (p.args_extra ?? []).map((v, i) => `arg${(p.args_named?.length ?? 0) + i}=${v}`)
  return [...named, ...extra].join(', ')
}

export function PacketRow({ packet: p, selected, showFrame, showEcho, onClick }: PacketRowProps) {
  return (
    <ContextMenuRoot>
      <ContextMenuTrigger>
        <div
          onClick={onClick}
          className="flex items-center text-xs font-mono cursor-pointer hover:bg-white/[0.03] color-transition"
          style={{
            opacity: p.is_unknown ? 0.5 : (p.ptype === 'NONE' || p.ptype === '0') ? 0.4 : 1,
          }}
        >
          {/* Expand indicator */}
          <span className={`py-1.5 px-1 ${col.chevron} shrink-0 flex items-center justify-center`}>
            <ChevronRight
              className="size-3 transition-transform duration-200 ease-out"
              style={{ color: selected ? colors.label : colors.textDisabled, transform: selected ? 'rotate(90deg)' : 'rotate(0deg)' }}
            />
          </span>
          <span className={`py-1.5 px-2 ${col.num} shrink-0 text-right tabular-nums`} style={{ color: selected ? colors.label : colors.dim }}>{p.num}</span>
          <span className={`py-1.5 px-2 ${col.time} shrink-0 tabular-nums whitespace-nowrap`} style={{ color: colors.dim }}>{p.time}</span>
          {showFrame && (
            <span className={`py-1.5 px-2 ${col.frame} shrink-0 whitespace-nowrap`} style={{ color: frameColor(p.frame) }}>{p.frame}</span>
          )}
          <span className={`py-1.5 px-2 ${col.node} shrink-0 whitespace-nowrap`}>
            <NodeName name={p.src} color={colors.label} />
          </span>
          {showEcho && (
            <span className={`py-1.5 px-2 ${col.node} shrink-0 whitespace-nowrap`} style={{ color: colors.warning }}>{p.echo}</span>
          )}
          <span className={`py-1.5 px-1 ${col.ptype} shrink-0`}><PtypeBadge ptype={p.ptype} /></span>
          <span className="py-1.5 px-2 flex-1 min-w-0 truncate">
            <span className="inline-block px-1.5 py-0 rounded-sm text-[11px] font-semibold" style={{ color: colors.value, backgroundColor: 'rgba(255,255,255,0.06)' }}>{p.cmd || '--'}</span>
            {importantArgs(p) && <span className="ml-2" style={{ color: colors.dim }}>{importantArgs(p)}</span>}
          </span>
          <span className={`py-1.5 px-2 ${col.flags} shrink-0`}>
            <span className="flex items-center gap-1 justify-end whitespace-nowrap">
              {p.crc16_ok === false && <Badge variant="destructive" className="text-[11px] px-1 py-0 h-5">CRC</Badge>}
              {p.is_echo && <Badge className="text-[11px] px-1 py-0 h-5" style={{ backgroundColor: `${colors.ulColor}22`, color: colors.ulColor }}>UL</Badge>}
              {p.is_dup && <Badge className="text-[11px] px-1 py-0 h-5" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>DUP</Badge>}
              {p.is_unknown && <Badge className="text-[11px] px-1 py-0 h-5" style={{ backgroundColor: `${colors.error}22`, color: colors.error }}>UNK</Badge>}
            </span>
          </span>
          <span className={`py-1.5 px-2 ${col.size} shrink-0 text-right tabular-nums whitespace-nowrap`} style={{ color: colors.dim }}>{p.size}B</span>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem icon={ClipboardCopy} onSelect={() => navigator.clipboard.writeText(p.cmd || '')}>
          Copy Command
        </ContextMenuItem>
        <ContextMenuItem icon={Braces} onSelect={() => navigator.clipboard.writeText(allArgs(p))}>
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
