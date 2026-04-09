import { useState, useEffect } from 'react'
import type { GssConfig } from '@/lib/types'

export function usePopOutBootstrap() {
  const [config, setConfig] = useState<GssConfig | null>(null)

  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(setConfig)
      .catch(() => {})
  }, [])

  return { config }
}
