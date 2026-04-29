import type { ColumnDef, RenderCell, RxPacket, TxQueueCmd, TxHistoryItem } from '@/lib/types'
import { frameColor } from '@/lib/colors'
import { packetFlags, rxTime } from '@/lib/rxPacket'

// Tailwind width tokens for platform-shell UI scaffolding (RX expand
// chevron + TX queue drag/number/action gutters). Mission-authored
// columns get their widths from `mission.yml::ui.{rx,tx}_columns[].width`
// — never from this list.
export const col = {
  chevron: 'w-5',       // expand indicator
  num:     'w-9',       // queue position number
  grip:    'w-[22px]',  // drag handle
  actions: 'w-[60px]',  // queue row buttons
} as const

// Platform RX shell columns. Each entry pairs a column def with a function
// that produces the cell from the packet — single source of truth per
// column. Mission-authored columns from `mission.yml::ui.rx_columns` slot
// in between PRE and POST in `composeRxColumns`.
const PLATFORM_RX_SHELL_PRE: ReadonlyArray<readonly [ColumnDef, (p: RxPacket) => RenderCell]> = [
  [{ id: 'num',   label: '#',     width: 'w-9',       align: 'right' },
    (p) => ({ value: p.num, tabular: true })],
  [{ id: 'time',  label: 'time',  width: 'w-[68px]' },
    (p) => ({ value: rxTime(p), monospace: true, tabular: true })],
  [{ id: 'frame', label: 'frame', width: 'w-[72px]', toggle: 'showFrame' },
    (p) => ({ value: p.frame || '--', monospace: true, tone: frameColor(p.frame || '') })],
]

const PLATFORM_RX_SHELL_POST: ReadonlyArray<readonly [ColumnDef, (p: RxPacket) => RenderCell]> = [
  [{ id: 'flags', label: '',     width: 'w-[72px]', align: 'right' },
    (p) => ({ value: packetFlags(p) })],
  [{ id: 'size',  label: 'size', width: 'w-10',     align: 'right' },
    (p) => ({ value: p.wire_len ?? p.size, suffix: 'B', tabular: true })],
]

const RX_SHELL_BUILDERS = new Map<string, (p: RxPacket) => RenderCell>([
  ...PLATFORM_RX_SHELL_PRE.map(([c, b]) => [c.id, b] as [string, (p: RxPacket) => RenderCell]),
  ...PLATFORM_RX_SHELL_POST.map(([c, b]) => [c.id, b] as [string, (p: RxPacket) => RenderCell]),
])

export function composeRxColumns(missionColumns: ColumnDef[]): ColumnDef[] {
  return [
    ...PLATFORM_RX_SHELL_PRE.map(([c]) => c),
    ...missionColumns,
    ...PLATFORM_RX_SHELL_POST.map(([c]) => c),
  ]
}

// TX columns are fully mission-declared (no platform shell). The verifiers
// tick strip is dispatched on `c.kind === 'verifiers'`.
export function buildRxRow(packet: RxPacket, columns: ColumnDef[]): Record<string, RenderCell> {
  const facts = packet.mission?.facts as Record<string, unknown> | undefined
  const row: Record<string, RenderCell> = {}
  for (const c of columns) {
    const shellBuild = RX_SHELL_BUILDERS.get(c.id)
    row[c.id] = shellBuild ? shellBuild(packet) : missionCell(c, facts)
  }
  return row
}

export function buildTxRow(
  item: TxQueueCmd | TxHistoryItem, columns: ColumnDef[],
): Record<string, RenderCell> {
  const facts = item.mission?.facts as Record<string, unknown> | undefined
  const row: Record<string, RenderCell> = {}
  for (const c of columns) {
    row[c.id] = missionCell(c, facts)
  }
  return row
}

function missionCell(
  c: ColumnDef, facts: Record<string, unknown> | undefined,
): RenderCell {
  if (c.kind === 'verifiers') {
    // CellValue dispatches on `c.kind` to render the verifier tick strip
    // from the per-row CommandInstance map. No path lookup.
    return { value: null }
  }
  const path = c.path ?? ''
  const value = path ? resolvePath(facts, path) : undefined
  return {
    value: formatCellValue(value),
    badge: Boolean(c.badge),
    monospace: !c.badge,
  }
}

function resolvePath(root: unknown, path: string): unknown {
  if (root == null || typeof root !== 'object') return undefined
  let cur: unknown = root
  for (const part of path.split('.')) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[part]
  }
  return cur
}

function formatCellValue(v: unknown): string {
  if (v == null || v === '') return '--'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
