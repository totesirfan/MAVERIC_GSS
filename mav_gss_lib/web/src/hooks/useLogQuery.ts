import { useState, useCallback } from 'react'
import { useDebouncedValue } from './useDebouncedValue'
import type { ColumnDef } from '@/lib/types'

type LogEntry = Record<string, unknown>
const PAGE_SIZE = 200

export function useLogQuery() {
  const [sessions, setSessions] = useState<Record<string, unknown>[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [currentOffset, setCurrentOffset] = useState(0)

  const [cmdFilter, setCmdFilter] = useState('')
  const [fromTime, setFromTime] = useState('')
  const [toTime, setToTime] = useState('')
  const [dateFilter, setDateFilter] = useState('')

  const debouncedCmd = useDebouncedValue(cmdFilter, 300)
  const debouncedFrom = useDebouncedValue(fromTime, 300)
  const debouncedTo = useDebouncedValue(toTime, 300)

  const [rxColumns, setRxColumns] = useState<ColumnDef[]>([])
  const [txColumns, setTxColumns] = useState<ColumnDef[]>([])

  const fetchSessions = useCallback(() => {
    fetch('/api/logs')
      .then((r) => r.json())
      .then((data: Record<string, unknown>[]) => setSessions(data))
      .catch(() => {})
  }, [])

  const fetchColumns = useCallback(() => {
    fetch('/api/columns')
      .then((r) => r.json())
      .then((data: ColumnDef[]) => setRxColumns(data))
      .catch(() => {})
    fetch('/api/tx-columns')
      .then((r) => r.json())
      .then((data: ColumnDef[]) => {
        // Wrap mission TX columns with platform-owned num/time/size for log viewer
        const full: ColumnDef[] = [
          { id: 'num', label: '#', align: 'right', width: 'w-9' },
          { id: 'time', label: 'time', width: 'w-[68px]' },
          ...data,
          { id: 'size', label: 'size', align: 'right', width: 'w-10' },
        ]
        setTxColumns(full)
      })
      .catch(() => {})
  }, [])

  const fetchEntries = useCallback((sessionId: string, append = false, offsetOverride = 0) => {
    setLoading(true)
    const params = new URLSearchParams()
    if (debouncedCmd) params.set('cmd', debouncedCmd)
    if (debouncedFrom) params.set('from', debouncedFrom)
    if (debouncedTo) params.set('to', debouncedTo)
    params.set('offset', String(offsetOverride))
    params.set('limit', String(PAGE_SIZE))
    fetch(`/api/logs/${sessionId}?${params.toString()}`)
      .then((r) => r.json())
      .then((data: { entries: LogEntry[]; has_more: boolean }) => {
        setEntries(prev => append ? [...prev, ...data.entries] : data.entries)
        setHasMore(data.has_more)
        setCurrentOffset(offsetOverride + data.entries.length)
        setLoading(false)
      })
      .catch(() => {
        setEntries([])
        setHasMore(false)
        setCurrentOffset(0)
        setLoading(false)
      })
  }, [debouncedCmd, debouncedFrom, debouncedTo])

  const reset = useCallback(() => {
    setSelected(null)
    setEntries([])
    setCmdFilter('')
    setFromTime('')
    setToTime('')
    setDateFilter('')
    setHasMore(false)
    setCurrentOffset(0)
  }, [])

  return {
    sessions,
    selected,
    setSelected,
    entries,
    loading,
    hasMore,
    currentOffset,
    cmdFilter,
    setCmdFilter,
    fromTime,
    setFromTime,
    toTime,
    setToTime,
    dateFilter,
    setDateFilter,
    debouncedCmd,
    debouncedFrom,
    debouncedTo,
    rxColumns,
    txColumns,
    fetchSessions,
    fetchColumns,
    fetchEntries,
    reset,
  }
}
