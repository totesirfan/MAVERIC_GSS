import { useEffect, useState, useCallback } from 'react'
import { colors, ptypeColor } from '@/lib/colors'
import type { LogSession } from '@/lib/types'
import { X, Search } from 'lucide-react'

interface LogEntry {
  num: number
  time_utc: string
  ptype: string
  cmd: string
  args: string
  size: number
  src: string
  dest: string
}

interface LogViewerProps {
  open: boolean
  onClose: () => void
}

export function LogViewer({ open, onClose }: LogViewerProps) {
  const [sessions, setSessions] = useState<LogSession[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [cmdFilter, setCmdFilter] = useState('')
  const [fromTime, setFromTime] = useState('')
  const [toTime, setToTime] = useState('')
  const [loading, setLoading] = useState(false)

  // Fetch session list on open
  useEffect(() => {
    if (!open) return
    fetch('/api/logs')
      .then((r) => r.json())
      .then((data: LogSession[]) => setSessions(data))
      .catch(() => {/* offline */})
  }, [open])

  // Fetch entries when session or filters change
  const fetchEntries = useCallback((sessionId: string) => {
    setLoading(true)
    const params = new URLSearchParams()
    if (cmdFilter) params.set('cmd', cmdFilter)
    if (fromTime) params.set('from', fromTime)
    if (toTime) params.set('to', toTime)
    const qs = params.toString()
    fetch(`/api/logs/${sessionId}${qs ? `?${qs}` : ''}`)
      .then((r) => r.json())
      .then((data: LogEntry[]) => {
        setEntries(data)
        setLoading(false)
      })
      .catch(() => {
        setEntries([])
        setLoading(false)
      })
  }, [cmdFilter, fromTime, toTime])

  useEffect(() => {
    if (selected) fetchEntries(selected)
  }, [selected, fetchEntries])

  // Reset state on close
  useEffect(() => {
    if (!open) {
      setSelected(null)
      setEntries([])
      setCmdFilter('')
      setFromTime('')
      setToTime('')
    }
  }, [open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex" style={{ backgroundColor: 'rgba(0,0,0,0.7)' }}>
      <div className="flex flex-1 m-4 rounded-lg border border-[#333] overflow-hidden"
           style={{ backgroundColor: colors.bgPanel }}>

        {/* Left sidebar: session list */}
        <div className="w-56 shrink-0 border-r border-[#333] flex flex-col overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 border-b border-[#333]">
            <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.label }}>
              Sessions
            </span>
            <button onClick={onClose} className="p-1 rounded hover:bg-white/5">
              <X className="size-3.5" style={{ color: colors.dim }} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {sessions.length === 0 ? (
              <div className="px-3 py-4 text-xs text-center" style={{ color: colors.dim }}>
                No log sessions found
              </div>
            ) : (
              sessions.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setSelected(s.id)}
                  className="w-full text-left px-3 py-2 text-xs border-b border-[#222] transition-colors hover:bg-white/5"
                  style={{
                    color: selected === s.id ? colors.label : colors.value,
                    backgroundColor: selected === s.id ? `${colors.label}11` : 'transparent',
                  }}
                >
                  <div className="font-medium truncate">{s.id}</div>
                  <div style={{ color: colors.dim }}>{s.packets} packets</div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Right area: search + entries */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Search bar */}
          <div className="flex items-center gap-2 px-3 py-2 border-b border-[#333]">
            <Search className="size-3.5 shrink-0" style={{ color: colors.dim }} />
            <input
              placeholder="Command filter..."
              className="flex-1 px-2 py-1 rounded text-xs outline-none border border-[#333] focus:border-[#555]"
              style={{ backgroundColor: colors.bgBase, color: colors.value }}
              value={cmdFilter}
              onChange={(e) => setCmdFilter(e.target.value)}
            />
            <input
              placeholder="From HH:MM"
              className="w-20 px-2 py-1 rounded text-xs outline-none border border-[#333] focus:border-[#555]"
              style={{ backgroundColor: colors.bgBase, color: colors.value }}
              value={fromTime}
              onChange={(e) => setFromTime(e.target.value)}
            />
            <input
              placeholder="To HH:MM"
              className="w-20 px-2 py-1 rounded text-xs outline-none border border-[#333] focus:border-[#555]"
              style={{ backgroundColor: colors.bgBase, color: colors.value }}
              value={toTime}
              onChange={(e) => setToTime(e.target.value)}
            />
          </div>

          {/* Entries */}
          <div className="flex-1 overflow-y-auto">
            {!selected ? (
              <div className="flex items-center justify-center h-full text-xs" style={{ color: colors.dim }}>
                Select a session to view entries
              </div>
            ) : loading ? (
              <div className="flex items-center justify-center h-full text-xs" style={{ color: colors.dim }}>
                Loading...
              </div>
            ) : entries.length === 0 ? (
              <div className="flex items-center justify-center h-full text-xs" style={{ color: colors.dim }}>
                No entries match the current filters
              </div>
            ) : (
              <div className="divide-y divide-[#222]">
                {entries.map((e, i) => (
                  <div key={i} className="flex items-center gap-3 px-3 py-1.5 text-xs hover:bg-white/3">
                    <span className="w-8 text-right shrink-0" style={{ color: colors.dim }}>
                      {e.num}
                    </span>
                    <span className="w-16 shrink-0" style={{ color: colors.dim }}>
                      {e.time_utc?.split(' ').pop()?.slice(0, 8) ?? '--'}
                    </span>
                    <span className="w-8 shrink-0 font-medium" style={{ color: ptypeColor(e.ptype) }}>
                      {e.ptype}
                    </span>
                    <span className="w-8 shrink-0" style={{ color: colors.dim }}>
                      {e.src}
                    </span>
                    <span className="w-8 shrink-0" style={{ color: colors.dim }}>
                      {e.dest}
                    </span>
                    <span className="font-medium" style={{ color: colors.value }}>
                      {e.cmd}
                    </span>
                    <span className="flex-1 truncate" style={{ color: colors.dim }}>
                      {e.args}
                    </span>
                    <span className="w-10 text-right shrink-0" style={{ color: colors.dim }}>
                      {e.size}B
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
