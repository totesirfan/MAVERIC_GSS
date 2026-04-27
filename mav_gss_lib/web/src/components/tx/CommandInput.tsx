import { useState, useRef, useCallback, useEffect, forwardRef } from 'react'
import { CornerDownLeft } from 'lucide-react'
import { Kbd } from '@/components/ui/kbd'
import { colors } from '@/lib/colors'
import { showToast } from '@/components/shared/overlays/StatusToast'
import type { CommandSchemaItem } from '@/lib/types'

interface CommandInputProps {
  onSubmit: (line: string) => void
  history: string[]
  onHistoryPush: (cmd: string) => void
  disabled?: boolean
  placeholderOverride?: string
}

// Raw CLI supports two grammars: shortcut `<cmd_id> [args...]` (first token
// is the cmd_id) and full `<dest> <cmd_id> [args...]` (second token). Look
// up both against the schema so the deprecation warning fires for either.
function findDeprecatedCmdId(line: string, schema: Record<string, CommandSchemaItem>): string | null {
  const tokens = line.trim().split(/\s+/)
  for (const t of [tokens[0], tokens[1]]) {
    if (!t) continue
    const k = t.toLowerCase()
    if (schema[k]?.deprecated) return k
  }
  return null
}

export const CommandInput = forwardRef<HTMLTextAreaElement, CommandInputProps>(
  function CommandInput({ onSubmit, history, onHistoryPush, disabled, placeholderOverride }, ref) {
  const [value, setValue] = useState('')
  const [histIdx, setHistIdx] = useState(-1)
  const [focused, setFocused] = useState(false)
  const [schema, setSchema] = useState<Record<string, CommandSchemaItem>>({})
  const internalRef = useRef<HTMLTextAreaElement>(null)
  const inputRef = (ref as React.RefObject<HTMLTextAreaElement | null>) ?? internalRef

  useEffect(() => {
    fetch('/api/schema')
      .then((r) => r.json())
      .then((data: Record<string, CommandSchemaItem>) => setSchema(data ?? {}))
      .catch(() => {})
  }, [])

  const submit = useCallback(() => {
    if (disabled) return
    const trimmed = value.trim()
    if (!trimmed) return
    const deprecatedCmd = findDeprecatedCmdId(trimmed, schema)
    if (deprecatedCmd) {
      showToast(`${deprecatedCmd} is deprecated`, 'warning', 'tx')
    }
    onSubmit(trimmed)
    onHistoryPush(trimmed)
    setValue('')
    setHistIdx(-1)
  }, [disabled, value, schema, onSubmit, onHistoryPush])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (disabled) return
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
  }, [disabled, value, history, histIdx, submit])

  const hasText = value.trim().length > 0
  const showCursor = focused && !hasText

  return (
    <div className="flex flex-col h-full">
      {/* Input row */}
      <div className="flex-1 flex items-center gap-2 px-3 min-h-0">
        <span
          className="font-mono text-[13px] leading-none select-none"
          style={{ color: colors.active }}
          aria-hidden="true"
        >❯</span>
        {showCursor && (
          <div
            className="w-0.5 h-[18px] rounded-sm shrink-0 animate-[blink_1.2s_ease-in-out_infinite]"
            style={{ backgroundColor: colors.active }}
          />
        )}
        <textarea
          ref={inputRef}
          className="flex-1 bg-transparent text-xs font-mono outline-none resize-none leading-5"
          style={disabled ? { color: colors.value, opacity: 0.5, cursor: 'not-allowed' } : { color: colors.value }}
          placeholder={placeholderOverride ?? 'Type a command...'}
          value={value}
          rows={1}
          disabled={disabled}
          onChange={(e) => { setValue(e.target.value); setHistIdx(-1) }}
          onKeyDown={handleKeyDown}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          spellCheck={false}
          autoComplete="off"
        />
      </div>
      {/* Kbd hints */}
      <div className="flex items-center gap-1.5 px-3 pb-1.5">
        <Kbd>↑</Kbd><Kbd>↓</Kbd>
        <span className="text-[10px]" style={{ color: colors.sep }}>history</span>
        <Kbd><CornerDownLeft className="size-2.5" /></Kbd>
        <span className="text-[10px]" style={{ color: colors.sep }}>queue</span>
      </div>
    </div>
  )
})
