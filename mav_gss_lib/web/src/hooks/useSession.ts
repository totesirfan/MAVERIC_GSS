import { useState, useEffect, useRef, useCallback } from 'react'
import { createSocket } from '@/lib/ws'
import { authFetch } from '@/lib/auth'

export interface SessionState {
  tag: string
  startedAt: string
  sessionId: string
  isTrafficActive: boolean
  openNewSession: boolean
  openRename: boolean
  setOpenNewSession: (v: boolean) => void
  setOpenRename: (v: boolean) => void
  startNewSession: (tag: string) => Promise<string | null>
  renameSession: (tag: string) => Promise<string | null>
  sessionResetGen: number
}

export function useSession(): SessionState {
  const [tag, setTag] = useState('untitled')
  const [startedAt, setStartedAt] = useState('')
  const [sessionId, setSessionId] = useState('')
  const [isTrafficActive, setIsTrafficActive] = useState(false)
  const [openNewSession, setOpenNewSession] = useState(false)
  const [openRename, setOpenRename] = useState(false)
  const [sessionResetGen, setSessionResetGen] = useState(0)
  const socketRef = useRef<ReturnType<typeof createSocket> | null>(null)

  // Hydrate from REST on mount
  useEffect(() => {
    authFetch('/api/session')
      .then(r => r.json())
      .then(data => {
        setTag(data.tag ?? 'untitled')
        setStartedAt(data.started_at ?? '')
        setSessionId(data.session_id ?? '')
        setIsTrafficActive(data.traffic_active ?? false)
      })
      .catch(() => {})
  }, [])

  // Connect to /ws/session
  useEffect(() => {
    const sock = createSocket('/ws/session', (data: unknown) => {
      const msg = data as Record<string, unknown>
      if (msg.type === 'session_new') {
        setTag((msg.tag as string) ?? 'untitled')
        setStartedAt((msg.started_at as string) ?? '')
        setSessionId((msg.session_id as string) ?? '')
        setSessionResetGen(g => g + 1)
      } else if (msg.type === 'session_renamed') {
        setTag((msg.tag as string) ?? 'untitled')
      } else if (msg.type === 'traffic_status') {
        setIsTrafficActive((msg.active as boolean) ?? false)
      } else if (msg.type === 'session_info') {
        setTag((msg.tag as string) ?? 'untitled')
        setStartedAt((msg.started_at as string) ?? '')
        setSessionId((msg.session_id as string) ?? '')
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
        body: JSON.stringify({ tag: newTag }),
      })
      const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }))
      if (!res.ok || data.ok === false) {
        // 207 partial success or 4xx/5xx failure
        return data.error ?? `Failed (${res.status})`
      }
      return null // success — state update comes via WS broadcast
    } catch (e) {
      return String(e)
    }
  }, [])

  const renameSession = useCallback(async (newTag: string): Promise<string | null> => {
    try {
      const res = await authFetch('/api/session', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag: newTag }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }))
        return data.error ?? `Failed (${res.status})`
      }
      return null // success — state update comes via WS broadcast
    } catch (e) {
      return String(e)
    }
  }, [])

  return {
    tag, startedAt, sessionId, isTrafficActive,
    openNewSession, openRename,
    setOpenNewSession, setOpenRename,
    startNewSession, renameSession,
    sessionResetGen,
  }
}
