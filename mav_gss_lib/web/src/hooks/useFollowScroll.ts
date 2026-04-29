import { useEffect, useRef, useState, useCallback, type RefObject } from 'react'

interface UseFollowScrollArgs {
  containerRef: RefObject<HTMLElement | null>
  // Selector value for the row we want centered. The container is queried
  // for `[data-follow-id="<target>"]` on every change of `target`.
  target: string | null
  // Reset-to-attached on this key's rising edge. Use 'idle' | 'active' so
  // the reset fires on every null→active transition, regardless of total.
  resetKey: 'idle' | 'active'
}

interface UseFollowScrollResult {
  detached: boolean
  /** 'up' if the target row is above the viewport, 'down' if below. */
  direction: 'up' | 'down'
  jumpToCurrent: () => void
}

/**
 * Center-on-change with detach-on-manual-scroll (spec §"Viewport follow-with-detach").
 *
 * - `target` change → smooth-scroll the matching row into vertical center.
 * - Listens to the container's `scroll` event, which fires for all causes —
 *   wheel, touch, keyboard (Arrow / PgUp / PgDn / Home / End), and
 *   programmatic. Programmatic scrolls (the auto-center call) are
 *   suppressed via a RAF flag; everything else sets `detached=true`.
 * - `direction` reports whether the chip should point ↑ or ↓ — based on
 *   the target row's current vertical position relative to the visible
 *   viewport. Updated on every container scroll.
 * - `jumpToCurrent()` re-centers and clears the detach.
 * - `resetKey` changing edge-wise re-attaches automatically (null→active).
 */
export function useFollowScroll({
  containerRef, target, resetKey,
}: UseFollowScrollArgs): UseFollowScrollResult {
  const [detachedState, setDetachedState] = useState({
    detached: false,
    resetKey,
  })
  const [direction, setDirection] = useState<'up' | 'down'>('down')
  const suppressRef = useRef(false)
  const detached = detachedState.resetKey === resetKey ? detachedState.detached : false

  const updateDirection = useCallback(() => {
    const c = containerRef.current
    if (!c || !target) return
    const el = c.querySelector<HTMLElement>(`[data-follow-id="${target}"]`)
    if (!el) return
    const cBox = c.getBoundingClientRect()
    const eBox = el.getBoundingClientRect()
    // Target row's center relative to the container's center.
    const targetCenter = eBox.top + eBox.height / 2
    const containerCenter = cBox.top + cBox.height / 2
    setDirection(targetCenter < containerCenter ? 'up' : 'down')
  }, [containerRef, target])

  const center = useCallback(() => {
    const c = containerRef.current
    if (!c || !target) return
    const el = c.querySelector<HTMLElement>(`[data-follow-id="${target}"]`)
    if (!el) return
    suppressRef.current = true
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    requestAnimationFrame(() => {
      requestAnimationFrame(() => { suppressRef.current = false })
    })
  }, [containerRef, target])

  // Auto-center on target change (when attached).
  useEffect(() => {
    if (detached) return
    center()
  }, [target, detached, center])

  // Single `scroll` listener catches every scroll cause (wheel, touch,
  // keyboard, programmatic). Programmatic scrolls fire while suppressRef
  // is true and are filtered out; user-driven scrolls flip detached.
  useEffect(() => {
    const c = containerRef.current
    if (!c) return
    const onScroll = () => {
      if (!suppressRef.current) {
        setDetachedState({ detached: true, resetKey })
      }
      updateDirection()
    }
    c.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      c.removeEventListener('scroll', onScroll)
    }
  }, [containerRef, resetKey, updateDirection])

  const jumpToCurrent = useCallback(() => {
    setDetachedState({ detached: false, resetKey })
    center()
  }, [center, resetKey])

  return { detached, direction, jumpToCurrent }
}
