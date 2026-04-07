import { useState, useRef, useCallback } from 'react'
import { Wrench, CornerDownLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { colors } from '@/lib/colors'

interface CommandInputProps {
  onSubmit: (line: string) => void
  onBuilderToggle?: () => void
}

export function CommandInput({ onSubmit, onBuilderToggle }: CommandInputProps) {
  const [value, setValue] = useState('')
  const [history, setHistory] = useState<string[]>([])
  const [histIdx, setHistIdx] = useState(-1)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const submit = useCallback(() => {
    if (!value.trim()) return
    onSubmit(value.trim())
    setHistory((prev) => [value.trim(), ...prev])
    setValue('')
    setHistIdx(-1)
  }, [value, onSubmit])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && value.trim()) {
      e.preventDefault()
      submit()
    } else if (e.key === 'ArrowUp' && !value.includes('\n')) {
      e.preventDefault()
      const nextIdx = Math.min(histIdx + 1, history.length - 1)
      setHistIdx(nextIdx)
      if (history[nextIdx]) setValue(history[nextIdx])
    } else if (e.key === 'ArrowDown' && !value.includes('\n')) {
      e.preventDefault()
      const nextIdx = histIdx - 1
      if (nextIdx < 0) { setHistIdx(-1); setValue('') }
      else { setHistIdx(nextIdx); setValue(history[nextIdx]) }
    }
  }, [value, history, histIdx, submit])

  const hasText = value.trim().length > 0

  return (
    <div className="flex overflow-hidden h-full">
      {/* Left: input + toolbar */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 px-3 pt-2 pb-1">
          <textarea
            ref={inputRef}
            className="flex-1 bg-transparent text-xs font-mono outline-none resize-none leading-5"
            style={{ color: colors.value }}
            placeholder="Type a command..."
            value={value}
            rows={1}
            onChange={(e) => { setValue(e.target.value); setHistIdx(-1) }}
            onKeyDown={handleKeyDown}
            spellCheck={false}
            autoComplete="off"
          />
        </div>
        <div className="flex items-center gap-1 px-2 pb-1.5">
          {onBuilderToggle && (
            <Button variant="ghost" size="sm" onClick={onBuilderToggle} className="h-6 px-2 rounded gap-1" title="Command Builder">
              <Wrench className="size-3" style={{ color: colors.dim }} />
              <span className="text-[11px]" style={{ color: colors.dim }}>Builder</span>
            </Button>
          )}
          <span className="text-[11px]" style={{ color: colors.sep }}>↑↓ history</span>
        </div>
      </div>

      {/* Right: Queue button — full height */}
      <button
        onClick={submit}
        disabled={!hasText}
        className="flex flex-col items-center justify-center px-4 gap-1 border-l transition-colors shrink-0 btn-feedback"
        style={{
          borderColor: colors.borderSubtle,
          backgroundColor: hasText ? colors.label : 'transparent',
          color: hasText ? colors.bgApp : colors.dim,
          cursor: hasText ? 'pointer' : 'default',
        }}
      >
        <CornerDownLeft className="size-4" />
        <span className="text-[11px] font-medium">Queue</span>
      </button>
    </div>
  )
}
