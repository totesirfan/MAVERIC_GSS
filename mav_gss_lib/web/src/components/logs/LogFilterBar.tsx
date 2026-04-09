import { Search } from 'lucide-react'
import { colors } from '@/lib/colors'
import { GssInput } from '@/components/ui/gss-input'

interface LogFilterBarProps {
  cmdFilter: string
  fromTime: string
  toTime: string
  entryCount: number
  hasSelection: boolean
  onCmdFilterChange: (v: string) => void
  onFromTimeChange: (v: string) => void
  onToTimeChange: (v: string) => void
}

export function LogFilterBar({
  cmdFilter, fromTime, toTime, entryCount, hasSelection,
  onCmdFilterChange, onFromTimeChange, onToTimeChange,
}: LogFilterBarProps) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 border-b" style={{ borderColor: colors.borderSubtle }}>
      <Search className="size-3.5 shrink-0" style={{ color: colors.dim }} />
      <GssInput
        placeholder="Command..."
        className="flex-1"
        value={cmdFilter}
        onChange={(e) => onCmdFilterChange(e.target.value)}
      />
      <GssInput
        placeholder="From HH:MM"
        className="w-24"
        value={fromTime}
        onChange={(e) => onFromTimeChange(e.target.value)}
      />
      <GssInput
        placeholder="To HH:MM"
        className="w-24"
        value={toTime}
        onChange={(e) => onToTimeChange(e.target.value)}
      />
      {hasSelection && <span className="text-[11px] shrink-0" style={{ color: colors.dim }}>{entryCount} entries</span>}
    </div>
  )
}
