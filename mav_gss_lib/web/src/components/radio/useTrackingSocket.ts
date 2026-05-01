import { useCallback, useEffect, useRef, useState } from 'react'
import { authFetch } from '@/lib/auth'
import { createSocket } from '@/lib/ws'
import type {
  DopplerCorrection,
  DopplerMode,
  TrackingWsMessage,
} from '@/lib/types'

export interface UseTrackingSocket {
  doppler: DopplerCorrection | null
  mode: DopplerMode
  error: string
  connected: boolean
  busy: 'engage' | 'disengage' | null
  actionError: string | null
  engage: () => Promise<void>
  disengage: () => Promise<void>
  dismissError: () => void
}

export function useTrackingSocket(): UseTrackingSocket {
  const [doppler, setDoppler] = useState<DopplerCorrection | null>(null)
  const [mode, setMode] = useState<DopplerMode>('disconnected')
  const [error, setError] = useState<string>('')
  const [connected, setConnected] = useState<boolean>(false)
  const [busy, setBusy] = useState<'engage' | 'disengage' | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const sockRef = useRef<{ close: () => void } | null>(null)

  useEffect(() => {
    const sock = createSocket(
      '/ws/tracking',
      (data) => {
        const msg = data as TrackingWsMessage
        if (msg.type === 'doppler') {
          setDoppler(msg.doppler)
          setMode(msg.doppler.mode)
          setError('')
        } else if (msg.type === 'status') {
          setMode(msg.mode)
          setError(msg.last_error || '')
        } else if (msg.type === 'error') {
          setError(msg.error)
        }
      },
      setConnected,
    )
    sockRef.current = sock
    return () => { sock.close() }
  }, [])

  // Reads the response body on success so the button label can flip even
  // when the WS is momentarily disconnected (the server-side broadcast would
  // reach no subscribers in that window). The WS push remains the source of
  // truth in steady state — this is just an optimistic top-up.
  const post = useCallback(async (path: string): Promise<{ mode?: string }> => {
    const r = await authFetch(path, { method: 'POST' })
    const body = await r.json().catch(() => ({}))
    if (!r.ok) {
      throw new Error(typeof body.error === 'string' ? body.error : `HTTP ${r.status}`)
    }
    return body
  }, [])

  const engage = useCallback(async () => {
    setBusy('engage')
    setActionError(null)
    try {
      const body = await post('/api/tracking/doppler/connection/connect')
      if (body.mode === 'connected' || body.mode === 'disconnected') setMode(body.mode)
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }, [post])

  const disengage = useCallback(async () => {
    setBusy('disengage')
    setActionError(null)
    try {
      const body = await post('/api/tracking/doppler/connection/disconnect')
      if (body.mode === 'connected' || body.mode === 'disconnected') setMode(body.mode)
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }, [post])

  const dismissError = useCallback(() => setActionError(null), [])

  return { doppler, mode, error, connected, busy, actionError, engage, disengage, dismissError }
}
