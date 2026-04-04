import { useState, useCallback, useRef, useEffect } from 'react'

interface SplitPaneProps {
  left: React.ReactNode
  right: React.ReactNode
  defaultRatio?: number
}

export function SplitPane({ left, right, defaultRatio = 0.5 }: SplitPaneProps) {
  const [ratio, setRatio] = useState(defaultRatio)
  const [dragging, setDragging] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setDragging(true)
  }, [])

  useEffect(() => {
    if (!dragging) return

    const onMouseMove = (e: MouseEvent) => {
      const container = containerRef.current
      if (!container) return
      const rect = container.getBoundingClientRect()
      const x = (e.clientX - rect.left) / rect.width
      setRatio(Math.min(0.8, Math.max(0.2, x)))
    }

    const onMouseUp = () => setDragging(false)

    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [dragging])

  return (
    <div ref={containerRef} className="flex flex-1 overflow-hidden" style={{ cursor: dragging ? 'col-resize' : undefined }}>
      <div className="overflow-hidden flex flex-col" style={{ width: `${ratio * 100}%` }}>
        {left}
      </div>
      <div
        onMouseDown={onMouseDown}
        className="flex-shrink-0 transition-colors"
        style={{
          width: '1px',
          backgroundColor: dragging ? '#00bfff' : '#333',
          cursor: 'col-resize',
        }}
        onMouseEnter={(e) => {
          if (!dragging) (e.currentTarget as HTMLElement).style.backgroundColor = '#555'
        }}
        onMouseLeave={(e) => {
          if (!dragging) (e.currentTarget as HTMLElement).style.backgroundColor = '#333'
        }}
      />
      <div className="overflow-hidden flex flex-col flex-1">
        {right}
      </div>
    </div>
  )
}
