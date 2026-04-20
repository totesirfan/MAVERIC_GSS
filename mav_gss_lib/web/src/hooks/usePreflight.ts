import { useState, useEffect, useRef, useCallback } from 'react'
import { createSocket } from '@/lib/ws'
import type {
  PreflightCheck,
  PreflightSummary,
  UpdatePhase,
  UpdateProgress,
  UpdateUIState,
} from '@/lib/types'

interface PreflightState {
  checks: PreflightCheck[]
  summary: PreflightSummary | null
  connected: boolean
  rerun: () => void
  updateState: UpdateUIState
  updatePhases: Record<UpdatePhase, UpdateProgress>
  showConfirm: () => void
  cancelConfirm: () => void
  applyUpdate: () => void
  signalLaunched: () => void
  reloadPage: () => void
}

const EMPTY_PHASES: Record<UpdatePhase, UpdateProgress> = {
  git_pull:  { phase: 'git_pull',  status: 'pending' },
  countdown: { phase: 'countdown', status: 'pending' },
  restart:   { phase: 'restart',   status: 'pending' },
}

/** Poll `/api/status` until the restarted uvicorn is accepting requests,
 *  then trigger a full page reload. Gives up after MAX_WAIT_MS and reloads
 *  anyway so the operator is never stuck on a stale page forever. */
async function waitForServerThenReload(signal: AbortSignal): Promise<void> {
  const INITIAL_GRACE_MS = 500   // let os.execv finish replacing the image
  const POLL_INTERVAL_MS = 400
  const POLL_TIMEOUT_MS  = 1500
  const MAX_WAIT_MS      = 30_000
  const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))
  await sleep(INITIAL_GRACE_MS)
  const deadline = Date.now() + MAX_WAIT_MS
  while (!signal.aborted && Date.now() < deadline) {
    try {
      const ctrl = new AbortController()
      const timer = setTimeout(() => ctrl.abort(), POLL_TIMEOUT_MS)
      const resp = await fetch('/api/status', { cache: 'no-store', signal: ctrl.signal })
      clearTimeout(timer)
      if (resp.ok) break
    } catch {
      // server not back yet — keep polling
    }
    await sleep(POLL_INTERVAL_MS)
  }
  if (!signal.aborted) window.location.reload()
}

export function usePreflight(): PreflightState {
  const [checks, setChecks] = useState<PreflightCheck[]>([])
  const [summary, setSummary] = useState<PreflightSummary | null>(null)
  const [connected, setConnected] = useState(false)
  const [updateState, setUpdateState] = useState<UpdateUIState>('idle')
  const [updatePhases, setUpdatePhases] = useState<Record<UpdatePhase, UpdateProgress>>(
    () => ({ ...EMPTY_PHASES }),
  )

  const socketRef = useRef<ReturnType<typeof createSocket> | null>(null)
  const hasLaunchedRef = useRef(false)
  const updateStateRef = useRef<UpdateUIState>('idle')
  const restartArmedRef = useRef(false)
  const reloadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reloadAbortRef = useRef<AbortController | null>(null)

  // Keep a ref mirror of updateState so the socket callbacks (stable closures)
  // can read the latest value without re-subscribing.
  useEffect(() => {
    updateStateRef.current = updateState
  }, [updateState])

  useEffect(() => {
    const sock = createSocket(
      '/ws/preflight',
      (data: unknown) => {
        const msg = data as Record<string, unknown>
        if (msg.type === 'check') {
          setChecks(prev => [...prev, msg as unknown as PreflightCheck])
        } else if (msg.type === 'summary') {
          setSummary(msg as unknown as PreflightSummary)
        } else if (msg.type === 'reset') {
          setChecks([])
          setSummary(null)
          setUpdatePhases({ ...EMPTY_PHASES })
          setUpdateState('idle')
          restartArmedRef.current = false
        } else if (msg.type === 'update_phase') {
          const phase = msg.phase as UpdatePhase
          const status = msg.status as UpdateProgress['status']
          const detail = msg.detail as string | undefined
          setUpdatePhases(prev => ({
            ...prev,
            [phase]: { phase, status, detail },
          }))
          if (status === 'fail') {
            setUpdateState('failed')
          }
          if (phase === 'restart' && status === 'running') {
            restartArmedRef.current = true
          }
        }
      },
      (isConnected: boolean) => {
        setConnected(isConnected)
        if (isConnected) {
          // Reset local state on every (re)connect so the backlog replay
          // the server sends on open does not duplicate prior-run results.
          setChecks([])
          setSummary(null)
          // Re-sync launched state after reconnect within the same page
          // lifetime. Cleared on page reload by React state reset.
          if (hasLaunchedRef.current) {
            socketRef.current?.send({ action: 'launched' })
          }
        } else {
          // WS disconnect during the 'restart' phase is the success signal
          // that os.execv has fired. Transition to 'reloading' and poll
          // /api/status until the new uvicorn is bound and serving, then
          // reload. A fixed timeout would either reload too early (broken
          // "can't reach this page" while the interpreter re-imports) or
          // too late. Polling adapts to the actual boot time.
          if (
            updateStateRef.current === 'applying'
            && restartArmedRef.current
          ) {
            setUpdateState('reloading')
            if (reloadTimerRef.current) clearTimeout(reloadTimerRef.current)
            reloadAbortRef.current?.abort()
            reloadAbortRef.current = new AbortController()
            void waitForServerThenReload(reloadAbortRef.current.signal)
          }
        }
      },
    )
    socketRef.current = sock
    return () => {
      sock.close()
      if (reloadTimerRef.current) {
        clearTimeout(reloadTimerRef.current)
        reloadTimerRef.current = null
      }
      reloadAbortRef.current?.abort()
      reloadAbortRef.current = null
    }
  }, [])

  const rerun = useCallback(() => {
    socketRef.current?.send({ action: 'rerun' })
    setUpdatePhases({ ...EMPTY_PHASES })
    setUpdateState('idle')
    restartArmedRef.current = false
  }, [])

  const showConfirm = useCallback(() => {
    setUpdateState('confirming')
  }, [])

  const cancelConfirm = useCallback(() => {
    setUpdateState('idle')
  }, [])

  const applyUpdate = useCallback(() => {
    setUpdatePhases({ ...EMPTY_PHASES })
    restartArmedRef.current = false
    setUpdateState('applying')
    socketRef.current?.send({ action: 'apply_update' })
  }, [])

  const signalLaunched = useCallback(() => {
    hasLaunchedRef.current = true
    socketRef.current?.send({ action: 'launched' })
  }, [])

  const reloadPage = useCallback(() => {
    window.location.reload()
  }, [])

  return {
    checks,
    summary,
    connected,
    rerun,
    updateState,
    updatePhases,
    showConfirm,
    cancelConfirm,
    applyUpdate,
    signalLaunched,
    reloadPage,
  }
}
