import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, Info, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { colors } from '@/lib/colors'
import { useAlarms } from '@/hooks/useAlarms'
import type { RxPacket, RxStatus } from '@/lib/types'

interface AlarmStripProps {
  status: RxStatus
  packets: RxPacket[]
  replayMode: boolean
  sessionResetGen?: number
}

const severityColor: Record<string, string> = {
  danger: colors.danger,
  warning: colors.warning,
  advisory: colors.info,
}

const severityFill: Record<string, string> = {
  danger: colors.dangerFill,
  warning: colors.warningFill,
  advisory: colors.infoFill,
}

const severityPulse: Record<string, string> = {
  danger: 'animate-pulse-danger',
  warning: 'animate-pulse-warning',
  advisory: '',
}

const severityIcon: Record<string, typeof AlertTriangle> = {
  danger: AlertCircle,
  warning: AlertTriangle,
  advisory: Info,
}

function formatAge(firstSeen: number): string {
  const s = Math.floor((Date.now() - firstSeen) / 1000)
  if (s < 5) return 'now'
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  return `${Math.floor(m / 60)}h${m % 60}m`
}

export function AlarmStrip({ status, packets, replayMode, sessionResetGen = 0 }: AlarmStripProps) {
  const { alarms, ackAll, ackOne } = useAlarms(status, packets, replayMode, sessionResetGen)

  // Highest severity drives the strip chrome
  const maxSeverity = alarms.length > 0
    ? (['danger', 'warning', 'advisory'] as const).find(s => alarms.some(a => a.severity === s)) ?? 'advisory'
    : 'advisory'

  const stripColor = severityColor[maxSeverity]
  const stripFill = severityFill[maxSeverity]
  const stripPulse = severityPulse[maxSeverity]
  const StripIcon = severityIcon[maxSeverity]

  return (
    <AnimatePresence>
      {alarms.length > 0 && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: 'easeOut' }}
          className="overflow-hidden shrink-0"
        >
          <div
            className={`flex items-center gap-3 px-4 py-1.5 text-xs font-mono ${stripPulse}`}
            style={{
              backgroundColor: stripFill,
              borderBottom: `1px solid ${stripColor}40`,
            }}
          >
            <div className="flex items-center gap-1.5 shrink-0">
              <StripIcon className="size-3.5" style={{ color: stripColor }} />
              <span className="font-bold" style={{ color: stripColor, fontFamily: 'Inter Variable, Inter, sans-serif' }}>
                {alarms.length} {alarms.length === 1 ? 'ALARM' : 'ALARMS'}
              </span>
            </div>

            <div className="w-px h-3.5 shrink-0" style={{ backgroundColor: `${stripColor}30` }} />

            <div className="flex items-center gap-3 flex-1 min-w-0 overflow-x-auto">
              {alarms.map(a => {
                const c = severityColor[a.severity]
                return (
                  <button
                    key={a.id}
                    onClick={() => ackOne(a.id)}
                    className="flex items-center gap-1.5 shrink-0 hover:opacity-70 transition-opacity cursor-pointer"
                    style={{ opacity: a.lingering ? 0.45 : a.acked ? 0.7 : 1 }}
                    title={`Click to acknowledge: ${a.label}`}
                  >
                    <span className="text-[9px]" style={{ color: c }}>●</span>
                    <span className="font-semibold" style={{ color: c }}>{a.label}</span>
                    <span style={{ color: `${c}CC` }}>{a.detail}</span>
                    {a.acked && !a.lingering && <span className="text-[10px]" style={{ color: `${c}99` }}>ACK</span>}
                    {a.id !== 'stale' && <span className="text-[10px]" style={{ color: `${c}88` }}>{formatAge(a.firstSeen)}</span>}
                  </button>
                )
              })}
            </div>

            <Button
              variant="ghost"
              size="sm"
              onClick={ackAll}
              className="shrink-0 h-6 px-2 text-[11px] font-medium"
              style={{ color: colors.textMuted, border: `1px solid ${colors.borderStrong}` }}
            >
              ACK ALL
            </Button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
