import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  Monitor,
  Play,
  Radio as RadioWave,
  RotateCcw,
  Square,
  Terminal,
  X,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { StatusDot } from '@/components/shared/atoms/StatusDot'
import { useConfig } from '@/state/sessionHooks'
import { colors } from '@/lib/colors'
import { cn } from '@/lib/utils'
import { lineColor } from './lineColor'
import { useRadioSocket, type RadioStatus } from './useRadioSocket'

function fmtUptime(startedAtMs: number | null, fallbackSeconds: number): string {
  const total = startedAtMs ? Math.max(0, Math.floor((Date.now() - startedAtMs) / 1000)) : Math.floor(fallbackSeconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

function basename(path: string): string {
  return path.split('/').filter(Boolean).pop() ?? path
}

function processDot(status: RadioStatus): { status: string; label: string } {
  switch (status.state) {
    case 'running':  return { status: 'LIVE',     label: 'RUNNING' }
    case 'stopping': return { status: 'STOPPING', label: 'STOPPING' }
    case 'crashed':  return { status: 'CRASHED',  label: 'CRASHED' }
    default:         return { status: 'STOPPED',  label: 'STOPPED' }
  }
}

function PanelHeader({ icon, title, right }: { icon: ReactNode; title: string; right?: ReactNode }) {
  return (
    <div className="flex min-h-[33px] shrink-0 items-center justify-between gap-3 border-b px-3 py-1.5" style={{ borderColor: colors.borderSubtle }}>
      <div className="flex min-w-0 items-center gap-2">
        {icon}
        <span className="truncate text-xs font-bold uppercase tracking-wide" style={{ color: colors.value }}>{title}</span>
      </div>
      {right}
    </div>
  )
}

function DataCell({
  label,
  value,
  tone,
  className,
  wrap = false,
}: {
  label: string
  value: string
  tone?: string
  className?: string
  wrap?: boolean
}) {
  return (
    <div className={cn('min-w-0 py-1', className)}>
      <div className="text-[10px] font-medium uppercase" style={{ color: colors.textMuted }}>{label}</div>
      <div
        title={value}
        className={cn('mt-0.5 min-w-0 font-mono text-xs', wrap ? 'break-all' : 'truncate')}
        style={{ color: tone ?? colors.textPrimary }}
      >
        {value}
      </div>
    </div>
  )
}

export function RadioPage() {
  const { config } = useConfig()
  const { status, logs, connected, lastUpdateMs, busy, actionError, runAction, dismissError } = useRadioSocket()
  const [apiStatus, setApiStatus] = useState<{ zmq_rx?: string; zmq_tx?: string }>({})
  const [, setNowTick] = useState(0)
  const [mountedAtMs] = useState(() => Date.now())
  const logRef = useRef<HTMLDivElement>(null)
  const stickyRef = useRef(true)

  useEffect(() => {
    let cancelled = false
    const refreshApiStatus = async () => {
      try {
        const r = await fetch('/api/status', { cache: 'no-store' })
        if (!r.ok) return
        const data = await r.json()
        if (cancelled) return
        setApiStatus(data as { zmq_rx?: string; zmq_tx?: string })
      } catch { /* ignore */ }
    }
    refreshApiStatus()
    const id = window.setInterval(refreshApiStatus, 3000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [])

  useEffect(() => {
    const id = window.setInterval(() => setNowTick(n => n + 1), 1000)
    return () => window.clearInterval(id)
  }, [])

  const connState: 'connecting' | 'connected' | 'disconnected' =
    !connected && Date.now() - mountedAtMs < 1500 ? 'connecting' : (connected ? 'connected' : 'disconnected')

  const onLogScroll = () => {
    const node = logRef.current
    if (!node) return
    stickyRef.current = node.scrollHeight - node.clientHeight - node.scrollTop < 32
  }

  useEffect(() => {
    const node = logRef.current
    if (node && stickyRef.current) node.scrollTop = node.scrollHeight
  }, [logs])

  const dot = processDot(status)
  const uptime = fmtUptime(status.started_at_ms, status.uptime_s)

  void lastUpdateMs
  void connState

  return (
    <div className="flex h-full min-h-0 flex-col p-4">
      {actionError && (
        <div
          className="mb-2 flex items-center justify-between gap-3 rounded-md border px-3 py-1.5 text-[11px]"
          style={{ color: colors.danger, borderColor: `${colors.danger}66`, backgroundColor: colors.dangerFill }}
          role="alert"
        >
          <span className="truncate">Action failed: {actionError}</span>
          <button onClick={dismissError} className="shrink-0 opacity-80 hover:opacity-100" aria-label="Dismiss error">
            <X className="size-3.5" />
          </button>
        </div>
      )}
      <div className="grid flex-1 min-h-0 grid-cols-[minmax(320px,0.72fr)_minmax(520px,1.28fr)] gap-3 max-[980px]:grid-cols-1 max-[980px]:overflow-y-auto">
        <div className="flex min-h-0 flex-col gap-3">
          <section className="flex flex-col rounded-lg border shadow-panel" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}>
            <PanelHeader
              icon={<Terminal className="size-3.5 shrink-0" style={{ color: colors.dim }} />}
              title="GNU Radio Process"
              right={<StatusDot status={dot.status} label={dot.label} />}
            />
            <div className="flex flex-col gap-1.5 px-3 py-2">
              <DataCell label="Script" value={basename(status.script) || '--'} />
              <div className="grid grid-cols-3 gap-x-4 gap-y-1">
                <DataCell label="PID" value={status.pid === null ? '--' : String(status.pid)} />
                <DataCell label="Uptime" value={status.running ? uptime : '00:00:00'} tone={status.running ? colors.success : colors.textMuted} />
                <DataCell label="Exit Code" value={status.exit_code === null ? '--' : String(status.exit_code)} tone={status.state === 'crashed' ? colors.danger : undefined} />
              </div>
            </div>
          </section>

          <section className="flex flex-col rounded-lg border shadow-panel" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}>
            <PanelHeader
              icon={<RadioWave className="size-3.5 shrink-0" style={{ color: colors.dim }} />}
              title="Runtime Control"
            />
            <div className="grid grid-cols-3 gap-2 px-3 py-2">
              <Button
                size="sm"
                variant="outline"
                disabled={!status.enabled || status.running || busy !== null}
                onClick={() => void runAction('start')}
                className="h-8 gap-1.5 text-xs font-bold btn-feedback"
                style={{ color: colors.active, borderColor: `${colors.active}66`, backgroundColor: `${colors.active}08` }}
              >
                <Play data-icon="inline-start" />
                Start
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!status.running || busy !== null}
                onClick={() => void runAction('stop')}
                className="h-8 gap-1.5 text-xs font-bold btn-feedback"
                style={{ color: colors.danger, borderColor: `${colors.danger}66`, backgroundColor: `${colors.danger}08` }}
              >
                <Square data-icon="inline-start" />
                Stop
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={!status.enabled || busy !== null}
                onClick={() => void runAction('restart')}
                className="h-8 gap-1.5 text-xs font-bold btn-feedback"
                style={{ color: colors.info, borderColor: `${colors.info}66`, backgroundColor: `${colors.info}08` }}
              >
                <RotateCcw data-icon="inline-start" />
                Restart
              </Button>
            </div>
          </section>

          <section className="flex flex-col rounded-lg border shadow-panel" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}>
            <PanelHeader
              icon={<RadioWave className="size-3.5 shrink-0" style={{ color: colors.dim }} />}
              title="ZMQ Links"
              right={(
                <Badge variant="outline" className="h-5 rounded text-[11px]" style={{ color: colors.textMuted, borderColor: colors.borderSubtle, backgroundColor: 'transparent' }}>
                  transport
                </Badge>
              )}
            />
            <div className="flex flex-col gap-2 px-3 py-2">
              <LinkRow label="RX" value={config?.platform.rx.zmq_addr ?? '--'} status={apiStatus.zmq_rx || 'DOWN'} />
              <LinkRow label="TX" value={config?.platform.tx.zmq_addr ?? '--'} status={apiStatus.zmq_tx || 'DOWN'} />
            </div>
          </section>

          <section className="flex min-h-0 flex-1 flex-col rounded-lg border shadow-panel" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}>
            <PanelHeader
              icon={<Monitor className="size-3.5 shrink-0" style={{ color: colors.dim }} />}
              title="Qt Flowgraph Window"
              right={(
                <Badge variant="outline" className="h-5 rounded text-[11px]" style={{ color: status.running ? colors.success : colors.textMuted, borderColor: colors.borderSubtle }}>
                  {status.running ? 'visible separately' : 'closed'}
                </Badge>
              )}
            />
            <div className="flex flex-1 flex-col gap-1.5 px-3 py-2">
              <DataCell label="Title" value="MAVERIC DUAL FRAME" />
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                <DataCell label="Mode" value="external Qt" tone={status.running ? colors.success : colors.textMuted} />
                <DataCell label="Autostart" value={status.autostart ? 'enabled' : 'disabled'} tone={status.autostart ? colors.warning : colors.textMuted} />
              </div>
              <DataCell label="CWD" value={status.cwd || '--'} wrap />
              {status.error && (
                <div className="rounded-md border px-2 py-1.5 text-[11px]" style={{ color: colors.danger, borderColor: `${colors.danger}44`, backgroundColor: colors.dangerFill }}>
                  {status.error}
                </div>
              )}
            </div>
          </section>
        </div>

        <section className="flex min-h-0 flex-col rounded-lg border shadow-panel" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}>
          <PanelHeader
            icon={<Terminal className="size-3.5 shrink-0" style={{ color: colors.dim }} />}
            title="GNU Radio Terminal"
            right={(
              <Badge variant="outline" className="h-5 rounded text-[11px]" style={{ color: connected ? colors.textSecondary : colors.textMuted, borderColor: colors.borderSubtle, backgroundColor: 'transparent' }}>
                stdout + stderr
              </Badge>
            )}
          />
          <div className="flex min-h-[32px] items-center gap-2 border-b px-3 py-1.5" style={{ borderColor: colors.borderSubtle }}>
            <span className="min-w-0 flex-1 truncate font-mono text-[11px]" style={{ color: colors.textMuted }}>
              {status.command.join(' ') || status.script || 'No radio process has been started'}
            </span>
          </div>
          <div ref={logRef} onScroll={onLogScroll} className="flex-1 min-h-0 overflow-auto p-2 font-mono text-[11px] leading-relaxed" style={{ backgroundColor: '#070707' }}>
            {logs.length === 0 ? (
              <div className="flex h-full items-center justify-center" style={{ color: colors.textMuted }}>
                No GNU Radio output yet
              </div>
            ) : logs.map((entry) => (
              <div key={entry.id} className="whitespace-pre-wrap break-words" style={{ color: lineColor(entry.text), minHeight: entry.text === '' ? '1.4em' : undefined }}>
                {entry.text || ' '}
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

function LinkRow({ label, value, status }: { label: string; value: string; status: string }) {
  return (
    <div className="min-w-0 py-1 text-[11px]">
      <div className="flex items-center gap-2">
        <span className="font-bold uppercase" style={{ color: colors.textMuted }}>{label}</span>
        <StatusDot status={status} />
      </div>
      <div title={value} className="mt-1 truncate font-mono text-xs" style={{ color: colors.textPrimary }}>
        {value}
      </div>
    </div>
  )
}
