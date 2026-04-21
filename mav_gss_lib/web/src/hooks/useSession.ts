import { useState, useEffect, useRef, useCallback } from 'react'
import { createSocket } from '@/lib/ws'
import { authFetch } from '@/lib/auth'

export interface SessionState {
  sessionTag: string
  startedAt: string
  sessionId: string
  operator: string
  host: string
  station: string
  isTrafficActive: boolean
  openNewSession: boolean
  openRename: boolean
  setOpenNewSession: (v: boolean) => void
  setOpenRename: (v: boolean) => void
  startNewSession: (tag: string) => Promise<string | null>
  renameSession: (tag: string) => Promise<string | null>
  sessionGeneration: number
}

export function useSession(): SessionState {
  const [sessionTag, setSessionTag] = useState('untitled')
  const [startedAt, setStartedAt] = useState('')
  const [sessionId, setSessionId] = useState('')
  const [operator, setOperator] = useState('')
  const [host, setHost] = useState('')
  const [station, setStation] = useState('')
  const [isTrafficActive, setIsTrafficActive] = useState(false)
  const [openNewSession, setOpenNewSession] = useState(false)
  const [openRename, setOpenRename] = useState(false)
  const [sessionGeneration, setSessionGeneration] = useState(0)
  const socketRef = useRef<ReturnType<typeof createSocket> | null>(null)

  useEffect(() => {
    authFetch('/api/session')
      .then(r => r.json())
      .then(data => {
        setSessionTag(data.session_tag ?? 'untitled')
        setStartedAt(data.started_at ?? '')
        setSessionId(data.session_id ?? '')
        setOperator(data.operator ?? '')
        setHost(data.host ?? '')
        setStation(data.station ?? '')
        setSessionGeneration(data.session_generation ?? 0)
        setIsTrafficActive(data.traffic_active ?? false)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    const sock = createSocket('/ws/session', (data: unknown) => {
      const msg = data as Record<string, unknown>
      if (msg.type === 'session_new') {
        setSessionTag((msg.session_tag as string) ?? 'untitled')
        setStartedAt((msg.started_at as string) ?? '')
        setSessionId((msg.session_id as string) ?? '')
        setOperator((msg.operator as string) ?? '')
        setHost((msg.host as string) ?? '')
        setStation((msg.station as string) ?? '')
        setSessionGeneration((msg.session_generation as number) ?? 0)
      } else if (msg.type === 'session_renamed') {
        setSessionTag((msg.session_tag as string) ?? 'untitled')
      } else if (msg.type === 'traffic_status') {
        setIsTrafficActive((msg.active as boolean) ?? false)
      } else if (msg.type === 'session_info') {
        setSessionTag((msg.session_tag as string) ?? 'untitled')
        setStartedAt((msg.started_at as string) ?? '')
        setSessionId((msg.session_id as string) ?? '')
        setOperator((msg.operator as string) ?? '')
        setHost((msg.host as string) ?? '')
        setStation((msg.station as string) ?? '')
        setSessionGeneration((msg.session_generation as number) ?? 0)
      }
    })

    socketRef.current = sock
    return () => sock.close()
  }, [])

  const startNewSession = useCallback(async (newTag: string): Promise<string | null> => {
    try {
      const res = await authFetch('/api/session/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_tag: newTag }),
      })
      const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }))
      if (!res.ok || data.ok === false) {
        return data.error ?? `Failed (${res.status})`
      }
      return null
    } catch (e) {
      return String(e)
    }
  }, [])

  const renameSession = useCallback(async (newTag: string): Promise<string | null> => {
    try {
      const res = await authFetch('/api/session', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_tag: newTag }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }))
        return data.error ?? `Failed (${res.status})`
      }
      return null
    } catch (e) {
      return String(e)
    }
  }, [])

  return {
    sessionTag, startedAt, sessionId,
    operator, host, station,
    isTrafficActive,
    openNewSession, openRename,
    setOpenNewSession, setOpenRename,
    startNewSession, renameSession,
    sessionGeneration,
  }
}
