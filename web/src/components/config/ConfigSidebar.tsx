import { useEffect, useRef, useState, useCallback } from 'react'
import { colors } from '@/lib/colors'
import type { GssConfig } from '@/lib/types'
import { X } from 'lucide-react'

/* ── helper sub-components ─────────────────────────────────────── */

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
      <span className="text-xs shrink-0" style={{ color: colors.dim }}>{label}</span>
      <input
        className="w-36 px-2 py-1 rounded text-xs text-right outline-none border border-[#333] focus:border-[#555]"
        style={{ backgroundColor: colors.bgBase, color: colors.value }}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className="flex items-center justify-between gap-2">
      <span className="text-xs shrink-0" style={{ color: colors.dim }}>{label}</span>
      <input
        type="number"
        className="w-36 px-2 py-1 rounded text-xs text-right outline-none border border-[#333] focus:border-[#555]"
        style={{ backgroundColor: colors.bgBase, color: colors.value }}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}

function ToggleField({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between gap-2 cursor-pointer">
      <span className="text-xs" style={{ color: colors.dim }}>{label}</span>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className="px-2 py-0.5 rounded text-xs font-medium transition-colors"
        style={{
          backgroundColor: value ? `${colors.success}22` : 'transparent',
          color: value ? colors.success : colors.dim,
          border: `1px solid ${value ? `${colors.success}44` : '#333'}`,
        }}
      >
        {value ? 'ON' : 'OFF'}
      </button>
    </label>
  )
}

/* ── main component ────────────────────────────────────────────── */

interface ConfigSidebarProps {
  open: boolean
  onClose: () => void
}

export function ConfigSidebar({ open, onClose }: ConfigSidebarProps) {
  const [cfg, setCfg] = useState<GssConfig | null>(null)
  const [dirty, setDirty] = useState(false)
  const initialRef = useRef<GssConfig | null>(null)

  // Fetch config on open
  useEffect(() => {
    if (!open) return
    fetch('/api/config')
      .then((r) => r.json())
      .then((data: GssConfig) => {
        setCfg(data)
        initialRef.current = JSON.parse(JSON.stringify(data))
        setDirty(false)
      })
      .catch(() => {/* offline */})
  }, [open])

  // Save on close if dirty
  const handleClose = useCallback(() => {
    if (dirty && cfg) {
      fetch('/api/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cfg),
      }).catch(() => {/* offline */})
    }
    onClose()
  }, [dirty, cfg, onClose])

  // Updater that marks dirty
  const update = useCallback(<K extends keyof GssConfig>(section: K, key: string, value: unknown) => {
    setCfg((prev) => {
      if (!prev) return prev
      const next = { ...prev, [section]: { ...prev[section], [key]: value } }
      setDirty(true)
      return next
    })
  }, [])

  if (!open) return null

  const isAx25 = cfg?.tx.uplink_mode?.toLowerCase().includes('ax25') ||
                  cfg?.tx.uplink_mode?.toLowerCase().includes('ax.25') ||
                  cfg?.tx.uplink_mode === 'Mode 6'

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div className="flex-1 bg-black/50" onClick={handleClose} />

      {/* Panel */}
      <div className="w-80 h-full overflow-y-auto p-4 border-l border-[#333]"
           style={{ backgroundColor: colors.bgPanel }}>
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm font-bold" style={{ color: colors.label }}>Configuration</span>
          <button onClick={handleClose} className="p-1 rounded hover:bg-white/5">
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
                      className="flex-1 px-2 py-1.5 rounded text-xs font-medium transition-colors"
                      style={{
                        backgroundColor: active ? `${colors.label}22` : 'transparent',
                        color: active ? colors.label : colors.dim,
                        border: `1px solid ${active ? `${colors.label}44` : '#333'}`,
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
              <NumberField label="Priority" value={cfg.csp.priority} onChange={(v) => update('csp', 'priority', v)} />
              <NumberField label="Source" value={cfg.csp.source} onChange={(v) => update('csp', 'source', v)} />
              <NumberField label="Destination" value={cfg.csp.destination} onChange={(v) => update('csp', 'destination', v)} />
              <NumberField label="Dest Port" value={cfg.csp.dest_port} onChange={(v) => update('csp', 'dest_port', v)} />
              <NumberField label="Src Port" value={cfg.csp.src_port} onChange={(v) => update('csp', 'src_port', v)} />
              <NumberField label="Flags" value={cfg.csp.flags} onChange={(v) => update('csp', 'flags', v)} />
            </Section>

            {/* System */}
            <Section title="System">
              <NumberField label="Frequency" value={cfg.tx.frequency} onChange={(v) => update('tx', 'frequency', v)} />
              <TextField label="ZMQ Address" value={cfg.tx.zmq_addr} onChange={(v) => update('tx', 'zmq_addr', v)} />
              <NumberField label="TX Delay (ms)" value={cfg.tx.delay_ms} onChange={(v) => update('tx', 'delay_ms', v)} />
            </Section>

            {dirty && (
              <div className="text-xs mt-2" style={{ color: colors.warning }}>
                Unsaved changes -- will save on close
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
