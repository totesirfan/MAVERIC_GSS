import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Shield } from 'lucide-react'
import { colors, frameColor } from '@/lib/colors'
import { PtypeBadge } from '@/components/shared/PtypeBadge'
import { getNodeFullName } from '@/lib/nodes'
import type { ColumnDef, DetailBlock, GssConfig, IntegrityBlock as IntegrityBlockType, RenderingFlag } from '@/lib/types'

// --- Row cell rendering (shared by PacketRow and LogViewer) ---

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

export function CellValue({ col: c, row, showFrame, showEcho, nodeDescriptions }: {
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

  // Node columns (src, dest, echo) — with tooltip
  if (c.id === 'src' || c.id === 'dest' || c.id === 'echo') {
    const nodeColor = c.id === 'echo' ? colors.warning : colors.label
    return (
      <span className={`py-1.5 px-1.5 ${width} whitespace-nowrap`}>
        <NodeName name={String(val ?? '')} color={nodeColor} nodeDescriptions={nodeDescriptions} />
      </span>
    )
  }

  // Cmd column — cmd ID pill + args
  if (c.id === 'cmd') {
    const raw = String(val ?? '')
    const spaceIdx = raw.indexOf(' ')
    const cmdId = spaceIdx > 0 ? raw.slice(0, spaceIdx) : raw
    const args = spaceIdx > 0 ? raw.slice(spaceIdx + 1) : ''
    return (
      <span className={`py-1.5 px-2 ${width}`}>
        <span className="inline-block px-1.5 py-0 rounded-sm text-[11px] font-semibold" style={{ color: colors.value, backgroundColor: 'rgba(255,255,255,0.06)' }}>
          {cmdId || '--'}
        </span>
        {args && <span className="ml-2" style={{ color: colors.dim }}>{args}</span>}
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

// --- Detail block rendering (shared by PacketDetail and LogViewer) ---

function F({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap">
      <span style={{ color: colors.sep }}>{label}:</span>
      <span style={{ color: color ?? colors.value }}>{value}</span>
    </span>
  )
}

export function SemanticBlocks({ blocks }: { blocks: DetailBlock[] }) {
  return (
    <>
      {blocks.map((block, bi) => (
        <div key={bi}>
          {block.label && block.kind !== 'time' && (
            <span className="text-[11px] font-medium mr-2" style={{ color: colors.sep }}>{block.label}</span>
          )}
          {block.kind === 'args' ? (
            <div className="space-y-0.5">
              {block.fields.map((f, fi) => (
                <div key={fi} className="flex items-center gap-2 text-xs pl-4">
                  <span style={{ color: colors.label }}>{f.name}</span>
                  <span style={{ color: colors.sep }}>=</span>
                  <span style={{ color: colors.value }}>{f.value}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-4">
              {block.fields.map((f, fi) => (
                <F key={fi} label={f.name} value={f.value} color={colors.label} />
              ))}
            </div>
          )}
        </div>
      ))}
    </>
  )
}

export function ProtocolBlocks({ blocks }: { blocks: DetailBlock[] }) {
  return (
    <>
      {blocks.map((block, bi) => (
        <div key={bi} className="text-xs whitespace-nowrap overflow-x-auto">
          <span className="font-medium mr-2" style={{ color: colors.sep }}>{block.label}</span>
          {block.fields.map((f, fi) => (
            <span key={fi} className="mr-3">
              <span style={{ color: colors.dim }}>{f.name}=</span>
              <span style={{ color: colors.value }}>{f.value}</span>
            </span>
          ))}
        </div>
      ))}
    </>
  )
}

export function IntegritySection({ blocks }: { blocks: IntegrityBlockType[] }) {
  return (
    <div className="flex items-center gap-2">
      <Shield className="size-3" style={{ color: colors.sep }} />
      {blocks.length === 0 ? (
        <span className="text-[11px]" style={{ color: colors.dim }}>No CRC data</span>
      ) : (
        blocks.map((b, i) => (
          <Badge key={i} variant={b.ok === false ? 'destructive' : 'secondary'} className="text-[11px] h-5">
            {b.label}: {b.ok === null ? '?' : b.ok ? 'OK' : 'FAIL'}
          </Badge>
        ))
      )}
    </div>
  )
}

/** Extract copyable command text from _rendering. */
export function extractFromRendering(rendering: { row?: { values: Record<string, unknown> }; detail_blocks?: DetailBlock[] } | undefined): { cmd: string; args: string } {
  const row = rendering?.row?.values
  if (row?.cmd) {
    return { cmd: String(row.cmd), args: String(row.cmd) }
  }
  const blocks = rendering?.detail_blocks ?? []
  let cmd = ''
  const argParts: string[] = []
  for (const block of blocks) {
    if (block.kind !== 'command') continue
    for (const f of block.fields ?? []) {
      if (f.name === 'Command') cmd = f.value
      else argParts.push(`${f.name}=${f.value}`)
    }
  }
  return { cmd, args: argParts.join(', ') }
}
