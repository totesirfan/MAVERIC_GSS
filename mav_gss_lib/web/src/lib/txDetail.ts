import type { DetailBlock, ParamUpdate, TxQueueCmd, TxHistoryItem } from '@/lib/types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function labelize(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function splitQualifiedName(name: string): [string, string] {
  const dot = name.indexOf('.')
  return dot >= 0 ? [name.slice(0, dot), name.slice(dot + 1)] : ['', name]
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') {
    return String(value)
  }
  if (Array.isArray(value)) return '[' + value.map(formatValue).join(', ') + ']'
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== null && v !== undefined && v !== '')
      .map(([k, v]) => `${k}: ${formatValue(v)}`)
    return '{' + entries.join(', ') + '}'
  }
  return String(value)
}

function fieldsFromRecord(value: Record<string, unknown>): Array<{ name: string; value: string }> {
  return Object.entries(value)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => ({ name: labelize(k), value: formatValue(v) }))
}

// Generic protocol/header blocks derived from TX item facts. Mirrors the
// RX `protocolBlocks` walker — every nested fact group becomes a block.
export function txDetailBlocks(item: TxQueueCmd | TxHistoryItem): DetailBlock[] {
  const facts = item.mission?.facts
  if (!isRecord(facts)) return []
  const blocks: DetailBlock[] = []
  for (const [name, value] of Object.entries(facts)) {
    if (value === null || value === undefined || value === '') continue
    if (isRecord(value)) {
      const fields = fieldsFromRecord(value)
      if (fields.length > 0) blocks.push({ kind: name, label: labelize(name), fields })
    } else {
      blocks.push({
        kind: name, label: labelize(name),
        fields: [{ name: labelize(name), value: formatValue(value) }],
      })
    }
  }
  return blocks
}

// Args from typed `parameters` tuple, grouped by name prefix (mirrors
// the RX `parameterBlocks` walker).
export function txParameterBlocks(item: TxQueueCmd | TxHistoryItem): DetailBlock[] {
  const params = item.parameters ?? []
  if (params.length === 0) return []
  const groups = new Map<string, ParamUpdate[]>()
  for (const param of params) {
    const [group] = splitQualifiedName(param.name)
    const label = group || 'args'
    groups.set(label, [...(groups.get(label) ?? []), param])
  }
  return Array.from(groups.entries()).map(([group, values]) => ({
    kind: 'args',
    label: labelize(group),
    fields: values.map((p) => {
      const [, key] = splitQualifiedName(p.name)
      const formatted = formatValue(p.value)
      return {
        name: labelize(key),
        value: p.unit ? `${formatted} ${p.unit}` : formatted,
      }
    }),
  }))
}
