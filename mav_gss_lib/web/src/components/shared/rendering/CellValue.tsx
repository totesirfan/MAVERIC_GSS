import { Badge } from '@/components/ui/badge'
import { colors, frameColor } from '@/lib/colors'
import { ValueBadge } from '@/components/shared/atoms/ValueBadge'
import type { ColumnDef, RenderCell, RenderingFlag } from '@/lib/types'

export function CellValue({ col: c, row, showFrame, showEcho }: {
  col: ColumnDef
  row: Record<string, RenderCell>
  showFrame: boolean
  showEcho: boolean
}) {
  if (c.toggle === 'showFrame' && !showFrame) return null
  if (c.toggle === 'showEcho' && !showEcho) return null

  const cell = row[c.id]
  const val = cell?.value
  const width = c.flex ? 'flex-1 min-w-0 truncate' : `${c.width ?? ''} shrink-0`
  const align = c.align === 'right' ? 'text-right' : ''

  if (cell?.badge) {
    return (
      <span className={`py-1.5 px-1 ${width}`}>
        <ValueBadge value={val as string | number} tone={cell.tone} />
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
    <span className={`py-1.5 px-2 ${width} ${align} whitespace-nowrap ${cell?.monospace ? 'font-mono' : ''}`} style={{ color: colors.dim }} title={cell?.tooltip ?? undefined}>
      {c.id === 'size' ? `${val}B` : String(val ?? '')}
    </span>
  )
}
