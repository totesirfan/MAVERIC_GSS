import { useRef, useState, useCallback, useEffect } from 'react'

export function useAutoScroll<T extends HTMLElement = HTMLDivElement>(depLength: number) {
  const ref = useRef<T>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  const onScroll = useCallback(() => {
    const el = ref.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setAutoScroll(atBottom)
  }, [])

  const scrollToBottom = useCallback(() => {
    const el = ref.current
    if (el) {
      el.scrollTop = el.scrollHeight
      setAutoScroll(true)
    }
  }, [])

  useEffect(() => {
    if (autoScroll) {
      const el = ref.current
      if (el) el.scrollTop = el.scrollHeight
    }
  }, [depLength, autoScroll])

  return { ref, autoScroll, setAutoScroll, onScroll, scrollToBottom }
}
