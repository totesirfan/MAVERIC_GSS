import { colors } from '@/lib/colors'
import { StatusDot } from '@/components/shared/StatusDot'
import { Button } from '@/components/ui/button'
import { Settings, HelpCircle, FileText } from 'lucide-react'

interface GlobalHeaderProps {
  version: string
  zmqRx: string
  zmqTx: string
  frequency: number
  uplinkMode: string
  onLogsClick: () => void
  onConfigClick: () => void
  onHelpClick: () => void
}

function modeColor(mode: string): string {
  const lower = mode.toLowerCase()
  if (lower.includes('golay') || lower === 'asm+golay' || lower === 'mode5') return colors.frameGolay
  if (lower.includes('ax25') || lower.includes('ax.25') || lower === 'mode6') return colors.frameAx25
  return colors.dim
}

export function GlobalHeader({
  version, zmqRx, zmqTx, frequency, uplinkMode,
  onLogsClick, onConfigClick, onHelpClick,
}: GlobalHeaderProps) {
  const freqStr = frequency ? `${(frequency / 1e6).toFixed(3)} MHz` : '--'

  return (
    <div className="flex items-center justify-between px-3 py-1.5 border-b border-[#333]"
         style={{ backgroundColor: colors.bgPanel }}>
      {/* Left */}
      <div className="flex items-center gap-3">
        <span className="font-bold tracking-wide" style={{ color: colors.label }}>
          MAVERIC GSS
        </span>
        <span className="text-xs" style={{ color: colors.dim }}>v{version}</span>
      </div>

      {/* Right */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-3">
          <span className="text-xs" style={{ color: colors.dim }}>RX</span>
          <StatusDot status={zmqRx} />
          <span className="text-xs" style={{ color: colors.dim }}>TX</span>
          <StatusDot status={zmqTx} />
        </div>

        <span className="text-xs" style={{ color: colors.dim }}>|</span>

        <span className="text-xs" style={{ color: colors.value }}>{freqStr}</span>

        <span className="text-xs font-medium" style={{ color: modeColor(uplinkMode) }}>
          {uplinkMode || '--'}
        </span>

        <span className="text-xs" style={{ color: colors.dim }}>|</span>

        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon-xs" onClick={onLogsClick} title="Logs">
            <FileText className="size-3.5" style={{ color: colors.dim }} />
          </Button>
          <Button variant="ghost" size="icon-xs" onClick={onConfigClick} title="Config">
            <Settings className="size-3.5" style={{ color: colors.dim }} />
          </Button>
          <Button variant="ghost" size="icon-xs" onClick={onHelpClick} title="Help">
            <HelpCircle className="size-3.5" style={{ color: colors.dim }} />
          </Button>
        </div>
      </div>
    </div>
  )
}
