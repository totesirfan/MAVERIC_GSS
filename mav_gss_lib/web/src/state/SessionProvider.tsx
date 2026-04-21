import { useState, useEffect, useMemo, type ReactNode } from 'react'
import { useSession } from '@/hooks/useSession'
import type { ColumnDef, ColumnDefs, GssConfig, TxColumnDef } from '@/lib/types'
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
      fetch('/api/tx-columns').then((r) => r.json() as Promise<TxColumnDef[]>),
      fetch('/api/columns').then((r) => r.json() as Promise<ColumnDef[]>),
    ])
      .then(([tx, rx]) => setColumns({ rx, tx }))
      .catch(() => {
        // On boot-time fetch failure, columns stays null and consumers render
        // empty column lists until the page reloads. `/api/columns` is served
        // from static mission schema so this only fires if the server is in a
        // badly broken state.
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
