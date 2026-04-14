import { GssInput } from '@/components/ui/gss-input'
import { colors } from '@/lib/colors'

interface FilenameInputProps {
  value: string
  onChange: (v: string) => void
  onEnter: () => void
  placeholder?: string
}

/**
 * Filename text input with a ghost `.jpg` suffix shown when the typed value
 * doesn't already end in `.jpg` / `.jpeg`. The suffix indicates the filename
 * will be auto-appended on send (see withJpg in helpers.ts).
 */
export function FilenameInput({ value, onChange, onEnter, placeholder = 'filename' }: FilenameInputProps) {
  const trimmed = value.trim()
  const needsSuffix = trimmed !== '' && !/\.jpe?g$/i.test(trimmed)
  return (
    <div className="relative flex-1">
      <GssInput
        className="w-full pr-9"
        placeholder={placeholder}
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') onEnter() }}
      />
      {needsSuffix && (
        <span
          className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] font-mono pointer-events-none"
          style={{ color: colors.dim }}
          title="auto-appended on send"
        >
          .jpg
        </span>
      )}
    </div>
  )
}
