import { AnimatePresence, motion } from 'framer-motion'
import { AlertCircle, AlertTriangle, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { colors } from '@/lib/colors'
import { type AlarmSeverity, useAlarms } from '@/hooks/useAlarms'

const severityColor: Record<AlarmSeverity, string> = {
  critical: colors.danger,
  warning: colors.warning,
  watch: colors.info,
}
const severityFill: Record<AlarmSeverity, string> = {
  critical: colors.dangerFill,
  warning: colors.warningFill,
  watch: colors.infoFill,
}
const severityPulse: Record<AlarmSeverity, string> = {
  critical: 'animate-pulse-danger',
  warning: 'animate-pulse-warning',
  watch: '',
}
const severityIcon: Record<AlarmSeverity, typeof AlertTriangle> = {
  critical: AlertCircle,
  warning: AlertTriangle,
  watch: Info,
}

function formatAge(firstSeen: number): string {
  const s = Math.floor((Date.now() - firstSeen) / 1000)
  if (s < 5) return 'now'
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  return `${Math.floor(m / 60)}h${m % 60}m`
}

export function AlarmStrip() {
  const { alarms, ackAll, ackOne } = useAlarms()

  const maxSeverity: AlarmSeverity = alarms.length > 0
    ? ((['critical', 'warning', 'watch'] as const).find(
        s => alarms.some(a => a.severity === s)
      ) ?? 'watch')
    : 'watch'

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
              <span
                className="font-bold"
                style={{ color: stripColor, fontFamily: 'Inter Variable, Inter, sans-serif' }}
              >
                {alarms.length} {alarms.length === 1 ? 'ALARM' : 'ALARMS'}
              </span>
            </div>

            <div className="w-px h-3.5 shrink-0" style={{ backgroundColor: `${stripColor}30` }} />

            <div className="flex items-center gap-3 flex-1 min-w-0 overflow-x-auto">
              {alarms.map(a => {
                const c = severityColor[a.severity]
                const dim =
                  a.state === 'unacked_cleared' ? 0.45 :
                  a.state === 'acked_active'    ? 0.7 : 1
                return (
                  <button
                    key={a.id}
                    onClick={() => ackOne(a.id)}
                    className="flex items-center gap-1.5 shrink-0 hover:opacity-70 transition-opacity cursor-pointer"
                    style={{ opacity: dim }}
                    title={`Click to acknowledge: ${a.label}`}
                  >
                    <span className="text-[9px]" style={{ color: c }}>●</span>
                    <span className="font-semibold" style={{ color: c }}>{a.label}</span>
                    <span style={{ color: `${c}CC` }}>{a.detail}</span>
                    {a.state === 'acked_active' && (
                      <span className="text-[10px]" style={{ color: `${c}99` }}>ACK</span>
                    )}
                    {a.id !== 'platform.silence' && (
                      <span className="text-[10px]" style={{ color: `${c}88` }}>
                        {formatAge(a.firstSeenMs)}
                      </span>
                    )}
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
