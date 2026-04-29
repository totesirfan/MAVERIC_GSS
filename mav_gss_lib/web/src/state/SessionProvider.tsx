import { useState, useEffect, useMemo, type ReactNode } from 'react'
import { useSession } from '@/hooks/useSession'
import { composeRxColumns } from '@/lib/columns'
import type { ColumnDef, ColumnDefs, GssConfig } from '@/lib/types'
import { SessionContext, type SessionContextValue } from './sessionContexts'

export function SessionProvider({ children }: { children: ReactNode }) {
  const session = useSession()
  const [config, setConfig] = useState<GssConfig | null>(null)
  const [columns, setColumns] = useState<ColumnDefs | null>(null)

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data: GssConfig) => setConfig(data))
      .catch(() => {})
  }, [])

  useEffect(() => {
    Promise.all([
      fetch('/api/rx-columns')
        .then((r) => r.json() as Promise<ColumnDef[]>)
        .catch(() => [] as ColumnDef[]),
      fetch('/api/tx-columns')
        .then((r) => r.json() as Promise<ColumnDef[]>)
        .catch(() => [] as ColumnDef[]),
    ]).then(([rxMission, tx]) => {
      setColumns({ rx: composeRxColumns(rxMission), tx })
    })
  }, [])

  // Destructure `session` so the memo depends on primitive-ish fields; the raw
  // `useSession()` return is a fresh object literal per render.
  const {
    sessionTag, startedAt, sessionId,
    operator, host, station,
    isTrafficActive,
    openNewSession, openRename,
    setOpenNewSession, setOpenRename,
    startNewSession, renameSession,
    sessionGeneration,
  } = session
  const value = useMemo<SessionContextValue>(
    () => ({
      sessionTag, startedAt, sessionId,
      operator, host, station,
      isTrafficActive,
      openNewSession, openRename,
      setOpenNewSession, setOpenRename,
      startNewSession, renameSession,
      sessionGeneration,
      config, setConfig, columns,
    }),
    [
      sessionTag, startedAt, sessionId,
      operator, host, station,
      isTrafficActive,
      openNewSession, openRename,
      setOpenNewSession, setOpenRename,
      startNewSession, renameSession,
      sessionGeneration,
      config, columns,
    ],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}
