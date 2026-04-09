import { useEffect } from 'react'

export interface Shortcut {
  key: string
  ctrl?: boolean
  meta?: boolean
  shift?: boolean
  action: () => void
  when?: () => boolean
}

export function useShortcuts(shortcuts: Shortcut[], enabled = true) {
  useEffect(() => {
    if (!enabled || shortcuts.length === 0) return
    const handler = (e: KeyboardEvent) => {
      for (const s of shortcuts) {
        const ctrlMatch = s.ctrl ? (e.ctrlKey || e.metaKey) : (!e.ctrlKey && !e.metaKey)
        const shiftMatch = s.shift ? e.shiftKey : !e.shiftKey
        if (e.key === s.key && ctrlMatch && shiftMatch && (!s.when || s.when())) {
          e.preventDefault()
          s.action()
          return
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [shortcuts, enabled])
}
