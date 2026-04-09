import { useState, useEffect, useRef } from 'react'
import { colors } from '@/lib/colors'

interface SessionBannerProps {
  sessionResetGen?: number
  sessionTag?: string
  packetCount: number
}

export function SessionBanner({ sessionResetGen, sessionTag, packetCount }: SessionBannerProps) {
  const bannerTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [bannerActive, setBannerActive] = useState(false)
  const [bannerTimedOut, setBannerTimedOut] = useState(false)
  const bannerTag = sessionTag || 'untitled'

  /* eslint-disable react-hooks/set-state-in-effect -- banner activation on session reset is intentional synchronous state */
  useEffect(() => {
    if (!sessionResetGen) return
    setBannerActive(true)
    setBannerTimedOut(false)
    if (bannerTimerRef.current) clearTimeout(bannerTimerRef.current)
    bannerTimerRef.current = setTimeout(() => setBannerTimedOut(true), 10_000)
    return () => { if (bannerTimerRef.current) clearTimeout(bannerTimerRef.current) }
  }, [sessionResetGen])
  /* eslint-enable react-hooks/set-state-in-effect */

  const show = bannerActive && packetCount === 0 && !bannerTimedOut

  if (!show) return null

  return (
    <div style={{
      textAlign: 'center', padding: '6px 16px',
      borderBottom: `1px solid ${colors.borderSubtle}`,
      fontFamily: "'JetBrains Mono', monospace", fontSize: '11px',
      color: colors.textMuted,
    }}>
      — session: {bannerTag} started —
    </div>
  )
}
