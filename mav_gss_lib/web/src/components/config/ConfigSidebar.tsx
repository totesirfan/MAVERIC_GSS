import { useEffect, useRef, useState, useCallback } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { colors } from '@/lib/colors'
import type { GssConfig } from '@/lib/types'
import { X, FileText, Database } from 'lucide-react'
import { authFetch } from '@/lib/auth'
import { GssInput } from '@/components/ui/gss-input'

const springConfig = { type: 'spring' as const, stiffness: 500, damping: 30, mass: 0.8 }
let hasLoadedConfigSidebar = false

/* -- helper sub-components ---------------------------------------- */

function InfoRow({ icon, label, value }: { icon?: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <span className="flex items-center gap-1.5 font-light shrink-0" style={{ color: colors.dim }}>
        {icon}
        {label}
      </span>
      <span className="font-mono text-right min-w-0 break-all" style={{ color: colors.value }}>{value}</span>
    </div>
  )
}

function Section({ title, children, show = true }: { title: string; children: React.ReactNode; show?: boolean }) {
  if (!show) return null
  return (
    <div className="mb-4">
      <div className="text-xs font-bold uppercase tracking-wider mb-2"
           style={{ color: colors.label }}>
        {title}
      </div>
      <div className="flex flex-col gap-2">{children}</div>
    </div>
  )
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex items-center justify-between gap-2">
      <span className="text-xs font-light shrink-0" style={{ color: colors.dim }}>{label}</span>
      <GssInput className="w-36 text-right" value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  )
}

function NumberField({ label, value, onChange, compact }: { label: string; value: number; onChange: (v: number) => void; compact?: boolean }) {
  return (
    <label className="flex items-center justify-between gap-2">
      <span className="text-xs font-light shrink-0" style={{ color: colors.dim }}>{label}</span>
      <GssInput type="number" className={`${compact ? 'w-16' : 'w-36'} text-right`} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  )
}

function ToggleField({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-2 cursor-pointer">
      <span className="text-xs font-light" style={{ color: colors.dim }}>{label}</span>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className="px-2 py-0.5 rounded text-xs font-medium color-transition"
        style={{
          backgroundColor: value ? `${colors.success}22` : 'transparent',
          color: value ? colors.success : colors.dim,
          border: `1px solid ${value ? `${colors.success}44` : colors.borderSubtle}`,
        }}
      >
        {value ? 'ON' : 'OFF'}
      </button>
    </label>
  )
}

/* -- main component ----------------------------------------------- */

interface ConfigSidebarProps {
  open: boolean
  onClose: () => void
}

export function ConfigSidebar({ open, onClose }: ConfigSidebarProps) {
  const [cfg, setCfg] = useState<GssConfig | null>(null)
  const [dirty, setDirty] = useState(false)
  const [statusInfo, setStatusInfo] = useState<{ version: string; schema_path: string; schema_count: number; log_dir: string; rx_log_json: string | null; rx_log_text: string | null; tx_log_json: string | null; tx_log_text: string | null } | null>(null)
  const initialRef = useRef<GssConfig | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<Element | null>(null)
  const animateOnMount = hasLoadedConfigSidebar

  useEffect(() => {
    hasLoadedConfigSidebar = true
  }, [])

  // Capture trigger element when opening
  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement
    }
  }, [open])

  // Focus trap: focus first input on mount, cycle Tab within panel, restore focus on close
  useEffect(() => {
    if (!open) {
      // Restore focus on close
      if (triggerRef.current && triggerRef.current instanceof HTMLElement) {
        triggerRef.current.focus()
      }
      return
    }

    const timer = setTimeout(() => {
      const panel = panelRef.current
      if (!panel) return
      const firstInput = panel.querySelector<HTMLElement>('input, button, [tabindex]')
      firstInput?.focus()
    }, 100)

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        handleCancel()
        return
      }
      if (e.key !== 'Tab') return
      const panel = panelRef.current
      if (!panel) return
      const focusable = panel.querySelectorAll<HTMLElement>(
        'input, button, [tabindex]:not([tabindex="-1"])'
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault()
          last.focus()
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      clearTimeout(timer)
      document.removeEventListener('keydown', handleKeyDown)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // Fetch config + status on open
  useEffect(() => {
    if (!open) return
    fetch('/api/config')
      .then((r) => r.json())
      .then((data: GssConfig) => {
        setCfg(data)
        initialRef.current = JSON.parse(JSON.stringify(data))
        setDirty(false)
      })
      .catch(() => {})
    fetch('/api/status')
      .then((r) => r.json())
      .then(setStatusInfo)
      .catch(() => {})
  }, [open])

  const handleSave = useCallback(() => {
    if (cfg) {
      authFetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      }).then(() => {
        initialRef.current = JSON.parse(JSON.stringify(cfg))
        setDirty(false)
      }).catch(() => {})
    }
  }, [cfg])

  const handleCancel = useCallback(() => {
    if (initialRef.current) setCfg(JSON.parse(JSON.stringify(initialRef.current)))
    setDirty(false)
    onClose()
  }, [onClose])

  // Updater that marks dirty
  const update = useCallback(<K extends keyof GssConfig>(section: K, key: string, value: unknown) => {
    setCfg((prev) => {
      if (!prev) return prev
      const next = { ...prev, [section]: { ...prev[section], [key]: value } }
      setDirty(true)
      return next
    })
  }, [])

  const isAx25 = cfg?.tx.uplink_mode?.toLowerCase().includes('ax25') ||
                  cfg?.tx.uplink_mode?.toLowerCase().includes('ax.25') ||
                  cfg?.tx.uplink_mode === 'Mode 6'

  return (
    <AnimatePresence initial={false}>
      {open && (
        <div className="fixed inset-0 z-50 flex">
          {/* Backdrop */}
          <motion.div
            className="flex-1"
            style={{ backgroundColor: 'rgba(0,0,0,0.7)' }}
            initial={animateOnMount ? { opacity: 0 } : false}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={handleCancel}
          />

          {/* Panel */}
          <motion.div
            ref={panelRef}
            className="w-96 h-full overflow-y-auto p-4 border-l shadow-overlay"
            style={{ backgroundColor: colors.bgPanelRaised, borderColor: colors.borderStrong }}
            initial={animateOnMount ? { x: 384 } : false}
            animate={{ x: 0 }}
            exit={{ x: 384 }}
            transition={springConfig}
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm font-bold" style={{ color: colors.label }}>Configuration</span>
              <button onClick={handleCancel} className="p-1 rounded hover:bg-white/5">
                <X className="size-4" style={{ color: colors.dim }} />
              </button>
            </div>

            {!cfg ? (
              <div className="text-xs" style={{ color: colors.dim }}>Loading...</div>
            ) : (
              <>
                {/* Uplink Mode */}
                <Section title="Uplink Mode">
                  <div className="flex gap-1">
                    {['AX.25', 'ASM+Golay'].map((mode) => {
                      const active = cfg.tx.uplink_mode === mode
                      return (
                        <button
                          key={mode}
                          onClick={() => update('tx', 'uplink_mode', mode)}
                          className="flex-1 px-2 py-1.5 rounded text-xs font-medium transition-colors btn-feedback"
                          style={{
                            backgroundColor: active ? `${colors.label}22` : 'transparent',
                            color: active ? colors.label : colors.dim,
                            border: `1px solid ${active ? `${colors.label}44` : colors.borderSubtle}`,
                          }}
                        >
                          {mode}
                        </button>
                      )
                    })}
                  </div>
                </Section>

                {/* AX.25 (conditional) */}
                <Section title="AX.25" show={isAx25}>
                  <TextField label="Src Call" value={cfg.ax25.src_call} onChange={(v) => update('ax25', 'src_call', v)} />
                  <NumberField label="Src SSID" value={cfg.ax25.src_ssid} onChange={(v) => update('ax25', 'src_ssid', v)} />
                  <TextField label="Dest Call" value={cfg.ax25.dest_call} onChange={(v) => update('ax25', 'dest_call', v)} />
                  <NumberField label="Dest SSID" value={cfg.ax25.dest_ssid} onChange={(v) => update('ax25', 'dest_ssid', v)} />
                </Section>

                {/* CSP */}
                <Section title="CSP">
                  <ToggleField label="CRC-32" value={cfg.csp.csp_crc} onChange={(v) => update('csp', 'csp_crc', v)} />
                  <NumberField label="Priority" value={cfg.csp.priority} onChange={(v) => update('csp', 'priority', v)} compact />
                  <NumberField label="Source" value={cfg.csp.source} onChange={(v) => update('csp', 'source', v)} compact />
                  <NumberField label="Destination" value={cfg.csp.destination} onChange={(v) => update('csp', 'destination', v)} compact />
                  <NumberField label="Dest Port" value={cfg.csp.dest_port} onChange={(v) => update('csp', 'dest_port', v)} compact />
                  <NumberField label="Src Port" value={cfg.csp.src_port} onChange={(v) => update('csp', 'src_port', v)} compact />
                  <NumberField label="Flags" value={cfg.csp.flags} onChange={(v) => update('csp', 'flags', v)} compact />
                </Section>

                {/* System */}
                <Section title="System">
                  <TextField label="Frequency" value={cfg.tx.frequency} onChange={(v) => update('tx', 'frequency', v)} />
                  <TextField label="ZMQ Address" value={cfg.tx.zmq_addr} onChange={(v) => update('tx', 'zmq_addr', v)} />
                  <NumberField label="TX Delay (ms)" value={cfg.tx.delay_ms} onChange={(v) => update('tx', 'delay_ms', v)} />
                </Section>

                {/* Session Info */}
                {statusInfo && (
                  <Section title="Session">
                    <InfoRow icon={<Database className="size-3" />} label="Version" value={statusInfo.version} />
                    <InfoRow icon={<FileText className="size-3" />} label="Schema" value={(statusInfo.schema_path || '').split('/').pop() ?? ''} />
                    <InfoRow label="Commands" value={String(statusInfo.schema_count)} />
                    <InfoRow label="Log Dir" value={statusInfo.log_dir} />
                    {statusInfo.rx_log_text && <InfoRow label="RX Log" value={statusInfo.rx_log_text.split('/').pop() ?? ''} />}
                    {statusInfo.rx_log_json && <InfoRow label="RX Data" value={statusInfo.rx_log_json.split('/').pop() ?? ''} />}
                    {statusInfo.tx_log_text && <InfoRow label="TX Log" value={statusInfo.tx_log_text.split('/').pop() ?? ''} />}
                    {statusInfo.tx_log_json && <InfoRow label="TX Data" value={statusInfo.tx_log_json.split('/').pop() ?? ''} />}
                  </Section>
                )}

                {/* Save / Cancel */}
                <div className="flex items-center gap-2 mt-4 pt-3 border-t" style={{ borderColor: colors.borderSubtle }}>
                  <button
                    onClick={handleCancel}
                    className="flex-1 px-3 py-1.5 rounded text-xs border"
                    style={{ color: colors.dim, borderColor: colors.borderSubtle }}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => { handleSave(); onClose() }}
                    disabled={!dirty}
                    className="flex-1 px-3 py-1.5 rounded text-xs font-bold disabled:opacity-30 btn-feedback"
                    style={{ backgroundColor: dirty ? colors.success : colors.borderSubtle, color: colors.bgApp }}
                  >
                    Save & Close
                  </button>
                </div>
              </>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
