import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { ChevronRight, ClipboardCopy, Braces, Binary } from 'lucide-react'
import { colors, frameColor } from '@/lib/colors'
import { col } from '@/lib/columns'
import { getNodeFullName } from '@/lib/nodes'
import { PtypeBadge } from '@/components/shared/PtypeBadge'
import {
  ContextMenuRoot,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
} from '@/components/shared/ContextMenu'
import type { ColumnDef, GssConfig, RenderingFlag, RxPacket } from '@/lib/types'

interface PacketRowProps {
  packet: RxPacket
  nodeDescriptions?: GssConfig['node_descriptions']
  selected: boolean
  showFrame: boolean
  showEcho: boolean
  columns?: ColumnDef[]
  onClick: () => void
}

function NodeName({ name, color, nodeDescriptions }: { name: string; color: string; nodeDescriptions?: GssConfig['node_descriptions'] }) {
  const full = getNodeFullName(name, nodeDescriptions)
  if (!full) return <span style={{ color }}>{name}</span>
  return (
    <TooltipProvider delay={300}>
      <Tooltip>
        <TooltipTrigger render={<span />} style={{ color }}>{name}</TooltipTrigger>
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

function CellValue({ col: c, row, showFrame, showEcho, nodeDescriptions }: {
  col: ColumnDef
  row: { values: Record<string, unknown>; _meta?: { opacity?: number } }
  showFrame: boolean
  showEcho: boolean
  nodeDescriptions?: GssConfig['node_descriptions']
}) {
  if (c.toggle === 'showFrame' && !showFrame) return null
  if (c.toggle === 'showEcho' && !showEcho) return null

  const val = row.values[c.id]
  const width = c.flex ? 'flex-1 min-w-0 truncate' : `${c.width ?? ''} shrink-0`
  const align = c.align === 'right' ? 'text-right' : ''

  // Badge column (ptype)
  if (c.badge) {
    return (
      <span className={`py-1.5 px-1 ${width}`}>
        <PtypeBadge ptype={val as string | number} />
      </span>
    )
  }

  // Flags column
  if (c.id === 'flags' && Array.isArray(val)) {
    const flags = val as RenderingFlag[]
    return (
      <span className={`py-1.5 px-2 ${width} ${align}`}>
        <span className="flex items-center gap-1 justify-end whitespace-nowrap">
          {flags.map((f, i) => (
            <Badge key={i} variant={f.tone === 'danger' ? 'destructive' : 'secondary'} className="text-[11px] px-1 py-0 h-5"
              style={f.tone !== 'danger' ? { backgroundColor: `${f.tone === 'warning' ? colors.warning : colors.ulColor}22`, color: f.tone === 'warning' ? colors.warning : colors.ulColor } : undefined}>
              {f.tag}
            </Badge>
          ))}
        </span>
      </span>
    )
  }

  // Node columns (src, echo) — with tooltip
  if (c.id === 'src' || c.id === 'echo') {
    const nodeColor = c.id === 'echo' ? colors.warning : colors.label
    return (
      <span className={`py-1.5 px-2 ${width} whitespace-nowrap`}>
        <NodeName name={String(val ?? '')} color={nodeColor} nodeDescriptions={nodeDescriptions} />
      </span>
    )
  }

  // Cmd column — display-ready string from backend, no re-parsing
  if (c.id === 'cmd') {
    return (
      <span className={`py-1.5 px-2 ${width}`} style={{ color: colors.value }}>
        {String(val ?? '') || '--'}
      </span>
    )
  }

  // Frame column — with color
  if (c.id === 'frame') {
    return (
      <span className={`py-1.5 px-2 ${width} whitespace-nowrap`} style={{ color: frameColor(String(val ?? '')) }}>
        {String(val ?? '')}
      </span>
    )
  }

  // Num column
  if (c.id === 'num') {
    return <span className={`py-1.5 px-2 ${width} tabular-nums ${align}`}>{String(val ?? '')}</span>
  }

  // Default text cell
  return (
    <span className={`py-1.5 px-2 ${width} ${align} whitespace-nowrap`} style={{ color: colors.dim }}>
      {c.id === 'size' ? `${val}B` : String(val ?? '')}
    </span>
  )
}

export function PacketRow({ packet: p, nodeDescriptions, selected, showFrame, showEcho, columns, onClick }: PacketRowProps) {
  return (
    <ContextMenuRoot>
      <ContextMenuTrigger>
        <div
          onClick={onClick}
          className="flex items-center text-xs font-mono cursor-pointer hover:bg-white/[0.03] color-transition"
          style={{
            opacity: p._rendering?.row?._meta?.opacity
              ?? (p.is_unknown ? 0.5 : (p.ptype === 'NONE' || p.ptype === '0') ? 0.4 : 1),
          }}
        >
          {/* Expand indicator */}
          <span className={`py-1.5 px-1 ${col.chevron} shrink-0 flex items-center justify-center`}>
            <ChevronRight
              className="size-3 transition-transform duration-200 ease-out"
              style={{ color: selected ? colors.label : colors.textDisabled, transform: selected ? 'rotate(90deg)' : 'rotate(0deg)' }}
            />
          </span>
          {(columns ?? []).length > 0 && p._rendering?.row ? (
            <>
              {columns!.map(c => (
                <CellValue key={c.id} col={c} row={p._rendering!.row}
                  showFrame={showFrame} showEcho={showEcho} nodeDescriptions={nodeDescriptions} />
              ))}
            </>
          ) : (
            <>
              <span className={`py-1.5 px-2 ${col.num} shrink-0 text-right tabular-nums`} style={{ color: selected ? colors.label : colors.dim }}>{p.num}</span>
              <span className={`py-1.5 px-2 ${col.time} shrink-0 tabular-nums whitespace-nowrap`} style={{ color: colors.dim }}>{p.time}</span>
              {showFrame && (
                <span className={`py-1.5 px-2 ${col.frame} shrink-0 whitespace-nowrap`} style={{ color: frameColor(p.frame) }}>{p.frame}</span>
              )}
              <span className={`py-1.5 px-2 ${col.node} shrink-0 whitespace-nowrap`}>
                <NodeName name={p.src} color={colors.label} nodeDescriptions={nodeDescriptions} />
              </span>
              {showEcho && (
                <span className={`py-1.5 px-2 ${col.node} shrink-0 whitespace-nowrap`}>
                  <NodeName name={p.echo} color={colors.warning} nodeDescriptions={nodeDescriptions} />
                </span>
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
            </>
          )}
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
