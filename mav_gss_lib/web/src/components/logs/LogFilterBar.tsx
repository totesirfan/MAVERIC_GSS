import { Search } from 'lucide-react'
import { colors } from '@/lib/colors'
import { GssInput } from '@/components/ui/gss-input'

interface LogFilterBarProps {
  labelFilter: string
  fromTime: string
  toTime: string
  entryCount: number
  hasSelection: boolean
  onLabelFilterChange: (v: string) => void
  onFromTimeChange: (v: string) => void
  onToTimeChange: (v: string) => void
}

export function LogFilterBar({
  labelFilter, fromTime, toTime, entryCount, hasSelection,
  onLabelFilterChange, onFromTimeChange, onToTimeChange,
}: LogFilterBarProps) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 border-b" style={{ borderColor: colors.borderSubtle }}>
      <Search className="size-3.5 shrink-0" style={{ color: colors.dim }} />
      <GssInput
        placeholder="Label..."
        className="flex-1"
        value={labelFilter}
        onChange={(e) => onLabelFilterChange(e.target.value)}
      />
      <GssInput
        placeholder="From HH:MM[:SS]"
        className="w-28"
        value={fromTime}
        onChange={(e) => onFromTimeChange(e.target.value)}
      />
      <GssInput
        placeholder="To HH:MM[:SS]"
        className="w-28"
        value={toTime}
        onChange={(e) => onToTimeChange(e.target.value)}
      />
      {hasSelection && <span className="text-[11px] shrink-0" style={{ color: colors.dim }}>{entryCount} entries</span>}
    </div>
  )
}
