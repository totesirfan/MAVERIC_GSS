import type { CatalogEntry, GncState } from '../types'
import { formatRegisterValue } from './formatValue'

/** Trigger a browser download of `content` as a file named `filename`.
 *  Uses a transient blob URL so no server round-trip is needed. */
function downloadBlob(content: string, filename: string, mime: string): void {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // Defer revoke — Firefox needs the URL alive briefly after click.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** RFC-4180 CSV escape: double quotes around any field that contains
 *  a comma, quote, newline, or leading/trailing whitespace; internal
 *  quotes are doubled. */
function csvEscape(field: string | number | boolean | null | undefined): string {
  const s = field == null ? '' : String(field)
  if (/[",\r\n]|^\s|\s$/.test(s)) {
    return '"' + s.replace(/"/g, '""') + '"'
  }
  return s
}

function tsStamp(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
}

/** One CSV row per register. Columns: Module, Reg, Name, Type, Unit,
 *  Value (formatted), Age (ms), Notes.
 *  `rows` is the filtered catalog slice the operator is currently viewing.
 *
 *  Raw Tokens / Last Seen (gs_ts) / Decode OK columns were dropped in
 *  v2 — raw tokens and packet provenance live in the RX log, and the
 *  extractor filters decode_ok=False entries before they reach state. */
export function exportRegistersCsv(
  rows: CatalogEntry[],
  state: GncState,
  nowMs: number,
): void {
  const header = [
    'Module', 'Reg', 'Name', 'Type', 'Unit',
    'Value', 'Age (ms)', 'Notes',
  ]
  const lines = [header.map(csvEscape).join(',')]
  for (const e of rows) {
    const snap = state[e.name]
    const age = snap?.t != null ? nowMs - snap.t : ''
    lines.push([
      e.module,
      e.register,
      e.name,
      e.type,
      e.unit,
      formatRegisterValue(snap),
      age,
      e.notes,
    ].map(csvEscape).join(','))
  }
  downloadBlob(lines.join('\n') + '\n', `gnc_registers_${tsStamp()}.csv`, 'text/csv')
}

/** Full-fidelity JSON export. Preserves nested decoded `value` shapes
 *  (bitfield flags, BCD dicts, NVG sensor payloads) that CSV flattens. */
export function exportRegistersJson(
  rows: CatalogEntry[],
  state: GncState,
  nowMs: number,
): void {
  const payload = {
    exported_at_ms: nowMs,
    exported_at_iso: new Date(nowMs).toISOString(),
    count: rows.length,
    registers: rows.map((e) => {
      const snap = state[e.name]
      return {
        ...e,
        snapshot: snap ?? null,
        age_ms: snap?.t != null ? nowMs - snap.t : null,
      }
    }),
  }
  downloadBlob(
    JSON.stringify(payload, null, 2) + '\n',
    `gnc_registers_${tsStamp()}.json`,
    'application/json',
  )
}
