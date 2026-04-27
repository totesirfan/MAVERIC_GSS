import { Switch } from '@/components/ui/switch'
import { colors } from '@/lib/colors'

interface TogglePillProps {
  label: string
  active: boolean
  onClick: () => void
}

export function TogglePill({ label, active, onClick }: TogglePillProps) {
  return (
    <label className="inline-flex items-center gap-1.5 cursor-pointer select-none" style={{ opacity: active ? 1 : 0.4 }}>
      <Switch
        size="sm"
        checked={active}
        onCheckedChange={onClick}
        className={active ? 'data-checked:bg-[#30C8E0]' : ''}
      />
      <span className="text-[11px] font-medium color-transition" style={{ color: active ? colors.active : colors.dim }}>
        {label}
      </span>
    </label>
  )
}
