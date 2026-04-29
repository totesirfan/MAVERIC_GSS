import { Badge } from '@/components/ui/badge'
import { colors } from '@/lib/colors'
import { ValueBadge } from '@/components/shared/atoms/ValueBadge'
import type { ColumnDef, RenderCell, RenderingFlag } from '@/lib/types'

function iconTokenForValue(
  value: unknown,
  valueIcons: Record<string, string> | undefined,
  defaultIcon: string | undefined,
): string | undefined {
  if (!valueIcons && !defaultIcon) return undefined
  const label = String(value ?? '')
  return valueIcons?.[label] ?? defaultIcon
}

// Pure dispatcher driven by cell properties — no platform-id awareness.
// Cells decide their own appearance via `flags` (array → flag badges),
// `badge` (truthy → ValueBadge), `tone`/`tabular`/`suffix`/`monospace`
// (text-cell variants).
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

  if (Array.isArray(val)) {
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

  if (cell?.badge) {
    return (
      <span className={`py-1.5 px-1 ${width}`}>
        <ValueBadge
          value={val as string | number}
          tone={cell.tone}
          iconToken={iconTokenForValue(val, c.value_icons, c.default_icon)}
        />
      </span>
    )
  }

  const text = `${val ?? ''}${cell?.suffix ?? ''}`
  return (
    <span
      className={`py-1.5 px-2 ${width} ${align} whitespace-nowrap ${cell?.monospace ? 'font-mono' : ''} ${cell?.tabular ? 'tabular-nums' : ''}`}
      style={{ color: cell?.tone ?? colors.dim }}
      title={cell?.tooltip ?? undefined}
    >
      {text}
    </span>
  )
}
