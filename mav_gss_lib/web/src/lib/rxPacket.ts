import type {
  DetailBlock,
  IntegrityBlock,
  RenderingFlag,
  RxPacket,
  ParamUpdate,
} from '@/lib/types'

export function rxTime(packet: RxPacket): string {
  const ms = packet.received_at_ms
  if (typeof ms !== 'number') return packet.time ?? ''
  return new Date(ms).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function rxTimestamp(packet: RxPacket): string {
  const ms = packet.received_at_ms
  if (typeof ms !== 'number') return packet.time_utc || packet.time || ''
  return new Date(ms).toLocaleString()
}

export function packetDisplayLabel(packet: RxPacket): string {
  return packet.mission?.id || packet.frame || 'Packet'
}

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

export function packetPayloadText(packet: RxPacket, options?: { compact?: boolean }): string {
  const facts = packet.mission?.facts
  if (isRecord(facts)) {
    const preferred = isRecord(facts.header) ? facts.header : facts
    const limit = options?.compact ? 4 : 8
    const parts = Object.entries(preferred)
      .filter(([, value]) => value !== null && value !== undefined && value !== '')
      .slice(0, limit)
      .map(([key, value]) => `${key}=${formatParamValue(value)}`)
    const hidden = Object.keys(preferred).length - parts.length
    if (parts.length > 0) {
      return hidden > 0 ? `${parts.join('  ')}  +${hidden}` : parts.join('  ')
    }
  }
  const params = packet.parameters ?? []
  if (params.length > 0) {
    const shown = params.slice(0, options?.compact ? 2 : params.length)
      .map((p) => `${p.name}=${formatParamValue(p.value)}${p.unit ? ` ${p.unit}` : ''}`)
    const hidden = params.length - shown.length
    return hidden > 0 ? `${shown.join('  ')}  +${hidden}` : shown.join('  ')
  }
  const bytes = packet.payload_len ?? packet.wire_len ?? packet.size
  return typeof bytes === 'number' ? `<${bytes} bytes>` : ''
}

export function packetFlags(packet: RxPacket): RenderingFlag[] {
  const flags: RenderingFlag[] = []
  const integrityOk = packet.flags?.integrity_ok
  if (integrityOk === false) flags.push({ tag: 'CRC', tone: 'danger' })
  if (packet.is_echo || packet.flags?.uplink_echo) flags.push({ tag: 'UL', tone: 'accent' })
  if (packet.is_dup || packet.flags?.duplicate) flags.push({ tag: 'DUP', tone: 'warning' })
  if (packet.is_unknown || packet.flags?.unknown) flags.push({ tag: 'UNK', tone: 'danger' })
  return flags
}

export function missionDetailBlocks(packet: RxPacket): DetailBlock[] {
  const fields = [
    ['Mission', packet.mission?.id ?? ''],
    ['Frame', packet.frame ?? ''],
    ['Payload bytes', String(packet.payload_len ?? '')],
    ['Wire bytes', String(packet.wire_len ?? packet.size ?? '')],
  ]
    .filter(([, value]) => value !== '')
    .map(([name, value]) => ({ name, value }))
  return fields.length > 0 ? [{ kind: 'packet', label: 'Packet', fields }] : []
}

export function protocolBlocks(packet: RxPacket): DetailBlock[] {
  const facts = packet.mission?.facts
  if (!isRecord(facts)) return []
  const blocks: DetailBlock[] = []
  for (const [name, value] of Object.entries(facts)) {
    if (value === null || value === undefined || value === '') continue
    if (isRecord(value)) {
      const fields = Object.entries(value)
        .filter(([, v]) => v !== null && v !== undefined && v !== '')
        .map(([k, v]) => ({ name: labelize(k), value: formatParamValue(v) }))
      if (fields.length > 0) blocks.push({ kind: name, label: labelize(name), fields })
    } else {
      blocks.push({ kind: name, label: labelize(name), fields: [{ name: labelize(name), value: formatParamValue(value) }] })
    }
  }
  return blocks
}

function formatParamValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') {
    return String(value)
  }
  if (Array.isArray(value)) {
    return '[' + value.map(formatParamValue).join(', ') + ']'
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== null && v !== undefined && v !== '')
      .map(([k, v]) => `${k}: ${formatParamValue(v)}`)
    return '{' + entries.join(', ') + '}'
  }
  return String(value)
}

export function parameterBlocks(packet: RxPacket): DetailBlock[] {
  const params = packet.parameters ?? []
  if (params.length === 0) return []
  const groups = new Map<string, ParamUpdate[]>()
  for (const param of params) {
    const [group] = splitQualifiedName(param.name)
    const label = group || 'parameters'
    groups.set(label, [...(groups.get(label) ?? []), param])
  }
  return Array.from(groups.entries()).map(([group, values]) => ({
    kind: 'args',
    label: labelize(group),
    fields: values.map((p) => {
      const [, key] = splitQualifiedName(p.name)
      const formatted = formatParamValue(p.value)
      return {
        name: labelize(key),
        value: p.unit ? `${formatted} ${p.unit}` : formatted,
      }
    }),
  }))
}

export function integrityBlocks(packet: RxPacket): IntegrityBlock[] {
  if (packet.flags?.integrity_ok === undefined) return []
  return [{
    kind: 'integrity',
    label: 'Integrity',
    scope: 'packet',
    ok: packet.flags.integrity_ok ?? null,
  }]
}
