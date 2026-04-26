import { useMemo, useState } from 'react'
import type { CatalogEntry, GncState } from '../types'
import { ageMs, formatAge, staleLevel, STALE_OPACITY, NO_DATA_OPACITY, type StaleLevel } from '../../shared/staleness'
import { colors } from '@/lib/colors'
import { formatRegisterValue } from './formatValue'
import { exportRegistersCsv, exportRegistersJson } from './exportTable'

interface RegistersTableProps {
  catalog: CatalogEntry[]
  state: GncState
  nowMs: number
}

/** Full register table — one row per catalog entry, overlaying live
 *  values from the platform parameter cache (projected by GNCPage).
 *  Rows group visually by module. Filtered by name/module search text. */
export function RegistersTable({ catalog, state, nowMs }: RegistersTableProps) {
  const [filter, setFilter] = useState('')

  // Register table lists addressable registers only. Non-register
  // canonical keys (GNC_MODE, GYRO_RATE_SRC, heartbeats, …) carry
  // module/register = null and are filtered out here — they're
  // consumed by dashboard cards, not by the register list.
  const registersOnly = useMemo(
    () => catalog.filter((e) => e.module !== null && e.register !== null),
    [catalog],
  )
  const filtered = useMemo(() => {
    if (!filter.trim()) return registersOnly
    const q = filter.trim().toLowerCase()
    return registersOnly.filter((e) => {
      return (
        e.name.toLowerCase().includes(q)          ||
        String(e.module).includes(q)              ||
        String(e.register).includes(q)            ||
        e.type.toLowerCase().includes(q)          ||
        e.notes.toLowerCase().includes(q)
      )
    })
  }, [registersOnly, filter])

  if (registersOnly.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-[11px] font-mono text-[#8A8A8A]">
        No register catalog available.
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Filter bar + export */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[#1a1a1a] bg-[#0a0a0a]">
        <span className="text-[11px] uppercase tracking-wide text-[#8A8A8A]">Filter</span>
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="name / module / type / notes…"
          className="flex-1 font-mono text-[11px] bg-transparent border border-[#222] rounded-sm px-2 py-1 text-[#E5E5E5] outline-none focus:border-[#444]"
        />
        <span className="font-mono text-[11px] text-[#555] min-w-[56px] text-right">
          {filtered.length}/{registersOnly.length}
        </span>
        <button
          type="button"
          onClick={() => exportRegistersCsv(filtered, state, nowMs)}
          className="font-sans text-[11px] uppercase tracking-wider px-2 py-1 border rounded-sm hover:bg-[#151515] transition-colors"
          style={{ color: colors.textPrimary, borderColor: '#222' }}
          title="Download current view as CSV"
        >
          Export CSV
        </button>
        <button
          type="button"
          onClick={() => exportRegistersJson(filtered, state, nowMs)}
          className="font-sans text-[11px] uppercase tracking-wider px-2 py-1 border rounded-sm hover:bg-[#151515] transition-colors"
          style={{ color: colors.textPrimary, borderColor: '#222' }}
          title="Download current view as JSON (full snapshot)"
        >
          Export JSON
        </button>
      </div>

      {/* Header */}
      <div className="grid gap-2 px-3 py-1.5 text-[11px] uppercase tracking-wide text-[#8A8A8A] font-sans border-b border-[#1a1a1a]"
           style={{ gridTemplateColumns: '46px 52px 180px 96px 1fr 52px 52px' }}>
        <div>Mod</div>
        <div>Reg</div>
        <div>Name</div>
        <div>Type</div>
        <div>Value</div>
        <div>Unit</div>
        <div className="text-right">Age</div>
      </div>

      {/* Rows */}
      <div className="flex-1 overflow-auto">
        {filtered.map((e) => {
          const snap = state[e.name]
          const age = ageMs(snap?.t ?? null, nowMs)
          const hasData = snap?.t != null
          const level: StaleLevel = hasData ? staleLevel(age) : 'critical'
          const opacity = hasData ? STALE_OPACITY[level] : NO_DATA_OPACITY
          const valueColor =
            level === 'critical' && hasData ? colors.danger :
            level === 'warning'              ? colors.warning :
                                               colors.textPrimary

          return (
            <div
              key={`${e.module}-${e.register}`}
              className="grid gap-2 px-3 py-1 border-b border-[#141414] hover:bg-[#0e0e0e] items-start"
              style={{
                gridTemplateColumns: '46px 52px 180px 96px 1fr 52px 52px',
                opacity,
              }}
              title={e.notes || undefined}
            >
              <div className="font-mono text-[11px] tabular-nums text-[#888]">{e.module}</div>
              <div className="font-mono text-[11px] tabular-nums text-[#888]">{e.register}</div>
              <div className="font-mono text-[11px] text-[#E5E5E5] break-all">{e.name}</div>
              <div className="font-mono text-[11px] text-[#8A8A8A] break-all">{e.type}</div>
              <div className="font-mono text-[11px] tabular-nums break-all whitespace-pre-wrap" style={{ color: valueColor }}>
                {formatRegisterValue(snap)}
              </div>
              <div className="font-mono text-[11px] text-[#8A8A8A] break-all">{e.unit}</div>
              <div className="font-mono text-[11px] text-[#555] text-right">
                {hasData ? formatAge(age) : '—'}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
