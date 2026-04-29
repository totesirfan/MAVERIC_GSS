import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Monitor,
  Play,
  Radio as RadioWave,
  RotateCcw,
  Square,
  Terminal,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { StatusDot } from '@/components/shared/atoms/StatusDot'
import { useConfig } from '@/state/sessionHooks'
import { authFetch } from '@/lib/auth'
import { createSocket } from '@/lib/ws'
import { colors } from '@/lib/colors'
import { cn } from '@/lib/utils'

interface RadioStatus {
  enabled: boolean
  autostart: boolean
  state: 'stopped' | 'running' | 'stopping' | 'crashed'
  running: boolean
  pid: number | null
  started_at_ms: number | null
  uptime_s: number
  exit_code: number | null
  error: string
  script: string
  cwd: string
  command: string[]
  log_lines: number
}

interface ApiStatus {
  zmq_rx?: string
  zmq_tx?: string
}

const DEFAULT_STATUS: RadioStatus = {
  enabled: false,
  autostart: false,
  state: 'stopped',
  running: false,
  pid: null,
  started_at_ms: null,
  uptime_s: 0,
  exit_code: null,
  error: '',
  script: '',
  cwd: '',
  command: [],
  log_lines: 1000,
}

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
  if (status.state === 'running') return { status: 'LIVE', label: 'RUNNING' }
  if (status.state === 'stopping') return { status: 'RETRY', label: 'STOPPING' }
  return { status: 'DOWN', label: status.state.toUpperCase() }
}

function lineColor(line: string): string {
  const lower = line.toLowerCase()
  if (lower.includes('warning')) return colors.warning
  if (lower.includes('error') || lower.includes('overflow') || lower.includes('underflow') || lower.includes('failed')) return colors.danger
  if (lower.includes('[info]') || lower.startsWith('info')) return colors.info
  if (line.includes('***** VERBOSE PDU DEBUG PRINT ******') || line.includes('************************************')) return colors.info
  if (line.startsWith('Executing:')) return colors.textPrimary
  return colors.textSecondary
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
  const [status, setStatus] = useState<RadioStatus>(DEFAULT_STATUS)
  const [apiStatus, setApiStatus] = useState<ApiStatus>({})
  const [logs, setLogs] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const [busy, setBusy] = useState<'start' | 'stop' | 'restart' | null>(null)
  const [, setNowTick] = useState(0)
  const logRef = useRef<HTMLDivElement>(null)
  const logLimitRef = useRef(DEFAULT_STATUS.log_lines)

  const refreshStatus = useCallback(() => {
    fetch('/api/radio/status', { cache: 'no-store' })
      .then(r => r.json())
      .then((data: RadioStatus) => setStatus({ ...DEFAULT_STATUS, ...data }))
      .catch(() => {})
  }, [])

  const refreshApiStatus = useCallback(() => {
    fetch('/api/status', { cache: 'no-store' })
      .then(r => r.json())
      .then((data: ApiStatus) => setApiStatus(data))
      .catch(() => {})
  }, [])

  useEffect(() => {
    logLimitRef.current = status.log_lines || DEFAULT_STATUS.log_lines
  }, [status.log_lines])

  useEffect(() => {
    refreshStatus()
    refreshApiStatus()
    fetch('/api/radio/logs', { cache: 'no-store' })
      .then(r => r.json())
      .then((data: { lines?: string[] }) => setLogs(Array.isArray(data.lines) ? data.lines : []))
      .catch(() => {})

    const sock = createSocket('/ws/radio', (data) => {
      const msg = data as Record<string, unknown>
      if (msg.type === 'status' && msg.status && typeof msg.status === 'object') {
        setStatus({ ...DEFAULT_STATUS, ...(msg.status as RadioStatus) })
      } else if (msg.type === 'logs' && Array.isArray(msg.lines)) {
        setLogs(msg.lines.map(String))
      } else if (msg.type === 'log') {
        const line = String(msg.line ?? '')
        setLogs(prev => {
          const limit = logLimitRef.current
          return [...prev, line].slice(-limit)
        })
      } else if (msg.type === 'exit' && msg.status && typeof msg.status === 'object') {
        setStatus({ ...DEFAULT_STATUS, ...(msg.status as RadioStatus) })
      }
    }, setConnected)

    const statusTimer = window.setInterval(refreshApiStatus, 3000)
    const clockTimer = window.setInterval(() => setNowTick(n => n + 1), 1000)
    return () => {
      sock.close()
      window.clearInterval(statusTimer)
      window.clearInterval(clockTimer)
    }
  }, [refreshApiStatus, refreshStatus])

  useEffect(() => {
    const node = logRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [logs])

  const runAction = useCallback(async (action: 'start' | 'stop' | 'restart') => {
    setBusy(action)
    try {
      const response = await authFetch(`/api/radio/${action}`, { method: 'POST' })
      if (response.ok) {
        const data = await response.json()
        setStatus({ ...DEFAULT_STATUS, ...data })
      }
    } finally {
      setBusy(null)
    }
  }, [])

  const dot = processDot(status)
  const command = useMemo(() => status.command.join(' '), [status.command])
  const uptime = fmtUptime(status.started_at_ms, status.uptime_s)

  return (
    <div className="flex-1 min-h-0 overflow-hidden p-4">
      <div className="grid h-full min-h-0 grid-cols-[minmax(320px,0.72fr)_minmax(520px,1.28fr)] gap-3 max-[980px]:grid-cols-1 max-[980px]:overflow-y-auto">
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
              {command || status.script || 'No radio process has been started'}
            </span>
          </div>
          <div ref={logRef} className="flex-1 min-h-0 overflow-auto p-2 font-mono text-[11px] leading-relaxed" style={{ backgroundColor: '#070707' }}>
            {logs.length === 0 ? (
              <div className="flex h-full items-center justify-center" style={{ color: colors.textMuted }}>
                No GNU Radio output yet
              </div>
            ) : logs.map((line, idx) => (
              <div key={`${idx}-${line}`} className="whitespace-pre-wrap break-words" style={{ color: lineColor(line), minHeight: line === '' ? '1.4em' : undefined }}>
                {line || ' '}
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
