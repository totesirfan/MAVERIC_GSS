import { colors } from '@/lib/colors'

interface TogglePillProps {
  label: string
  active: boolean
  onClick: () => void
}

export function TogglePill({ label, active, onClick }: TogglePillProps) {
  return (
    <button
      onClick={onClick}
      className="px-2 py-0.5 rounded text-xs font-medium transition-colors"
      style={{
        backgroundColor: active ? `${colors.success}22` : 'transparent',
        color: active ? colors.success : colors.dim,
        border: `1px solid ${active ? `${colors.success}44` : '#333'}`,
      }}
    >
      {label}
    </button>
  )
}
