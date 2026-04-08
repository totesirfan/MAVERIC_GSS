import { useState, useEffect, useMemo, useRef } from 'react'
import { CornerDownLeft, X } from 'lucide-react'
import { colors } from '@/lib/colors'
import { PtypeBadge } from '@/components/shared/PtypeBadge'
import type { MissionBuilderProps } from '@/lib/types'

interface CommandArg {
  name: string
  type: string
  important?: boolean
}

interface CommandDef {
  dest?: string
  echo?: string
  ptype?: string
  nodes?: string[]
  tx_args?: CommandArg[]
  rx_only?: boolean
  guard?: boolean
}

type CommandSchema = Record<string, CommandDef>

interface GssNodes {
  nodes: Record<number, string>
  general: { gs_node?: string }
}

export default function MavericTxBuilder({ onQueue, onClose }: MissionBuilderProps) {
  const [schema, setSchema] = useState<CommandSchema | null>(null)
  const [config, setConfig] = useState<GssNodes | null>(null)
  const [destNode, setDestNode] = useState<string | null>(null)
  const [selectedCmd, setSelectedCmd] = useState<string | null>(null)
  const [argValues, setArgValues] = useState<Record<string, string>>({})
  const [echo, setEcho] = useState('NONE')
  const [showEcho, setShowEcho] = useState(false)
  const [search, setSearch] = useState('')
  const firstArgRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    fetch('/api/schema')
      .then((r) => r.json())
      .then((data: CommandSchema) => setSchema(data))
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((data: GssNodes) => setConfig(data))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (selectedCmd) setTimeout(() => firstArgRef.current?.focus(), 50)
  }, [selectedCmd])

  const gsNodeName = config?.general?.gs_node ?? ''
  const nodes = useMemo(() => {
    if (!config?.nodes) return []
    return Object.entries(config.nodes)
      .map(([id, name]) => ({ id: Number(id), name }))
      .filter(n => n.id !== 0 && n.name !== String(gsNodeName))
  }, [config, gsNodeName])

  const filteredCmds = useMemo(() => {
    if (!schema) return []
    let entries = Object.entries(schema).filter(([, def]) => !def.rx_only)
    if (destNode) {
      entries = entries.filter(([, def]) => !def.nodes || def.nodes.length === 0 || def.nodes.includes(destNode))
    }
    if (search) {
      const lower = search.toLowerCase()
      entries = entries.filter(([name]) => name.toLowerCase().includes(lower))
    }
    return entries
  }, [schema, search, destNode])

  const cmdDef: CommandDef | null = selectedCmd && schema ? schema[selectedCmd] ?? null : null
  const txArgs = cmdDef?.tx_args ?? []

  function pickNode(name: string) {
    setDestNode(name)
    setSelectedCmd(null)
    setArgValues({})
    setSearch('')
  }

  function pickCmd(name: string) {
    setSelectedCmd(name)
    setArgValues({})
    const def = schema?.[name]
    setEcho(def?.echo ?? 'NONE')
    setSearch('')
  }

  function handleQueue() {
    if (!selectedCmd || !destNode) return
    onQueue({
      cmd_id: selectedCmd,
      args: argValues,
      dest: destNode,
      echo: echo || 'NONE',
      ptype: cmdDef?.ptype ?? 'CMD',
      guard: cmdDef?.guard ?? false,
    })
    setArgValues({})
    setSelectedCmd(null)
    setSearch('')
  }

  const inputCls = "w-full bg-transparent border border-[#222222] rounded px-2 py-1 text-xs outline-none focus:border-[#30C8E0] focus:ring-1 focus:ring-[#30C8E0]/20"

  const preview = selectedCmd && destNode
    ? `${destNode} ${echo !== 'NONE' ? echo + ' ' : ''}${cmdDef?.ptype || 'CMD'} ${selectedCmd} ${Object.values(argValues).filter(Boolean).join(' ')}`.trim()
    : ''

  return (
    <div
      className="flex flex-col overflow-y-auto h-full"
      onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); onClose() } }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0" style={{ borderColor: colors.borderSubtle }}>
        <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.label }}>Build Command</span>
        <div className="flex-1" />
        <button onClick={onClose} className="p-0.5 rounded hover:bg-white/5">
          <X className="size-3" style={{ color: colors.dim }} />
        </button>
      </div>

      <div className="p-2 space-y-2">
        {/* 1. Destination node */}
        <div>
          <div className="text-[11px] font-medium mb-1" style={{ color: colors.dim }}>Destination</div>
          <div className="flex flex-wrap gap-1">
            {nodes.map((n) => {
              const active = destNode === n.name
              return (
                <button
                  key={n.id}
                  onClick={() => pickNode(n.name)}
                  className="px-2 py-0.5 rounded text-[11px] font-medium border color-transition btn-feedback"
                  style={{
                    borderColor: active ? colors.label : colors.borderSubtle,
                    backgroundColor: active ? `${colors.label}18` : 'transparent',
                    color: active ? colors.label : colors.dim,
                  }}
                >
                  {n.name}
                </button>
              )
            })}
          </div>
        </div>

        {/* 2. Command picker */}
        {destNode && (
          <div>
            <div className="text-[11px] font-medium mb-1" style={{ color: colors.dim }}>Command</div>
            <input
              autoFocus={!selectedCmd}
              type="text"
              className={`${inputCls} mb-1`}
              style={{ color: colors.value }}
              placeholder="Filter..."
              value={search}
              onChange={(e) => { setSearch(e.target.value); if (selectedCmd) setSelectedCmd(null) }}
            />
            <div className="max-h-28 overflow-y-auto rounded border" style={{ borderColor: colors.borderSubtle }}>
              {filteredCmds.length === 0 ? (
                <div className="text-[11px] py-2 text-center" style={{ color: colors.dim }}>No commands</div>
              ) : (
                filteredCmds.map(([name, def]) => {
                  const active = selectedCmd === name
                  return (
                    <button
                      key={name}
                      onClick={() => pickCmd(name)}
                      className="flex items-center gap-1.5 w-full text-left px-2 py-1 text-xs hover:bg-white/[0.04] color-transition"
                      style={{
                        backgroundColor: active ? `${colors.label}11` : undefined,
                        borderLeft: active ? `2px solid ${colors.label}` : '2px solid transparent',
                      }}
                    >
                      <span className="font-medium" style={{ color: active ? colors.label : colors.value }}>{name}</span>
                      {def.ptype && <PtypeBadge ptype={def.ptype} />}
                      {def.tx_args && def.tx_args.length > 0 && (
                        <span className="text-[11px] ml-auto" style={{ color: colors.dim }}>
                          {def.tx_args.length} arg{def.tx_args.length !== 1 ? 's' : ''}
                        </span>
                      )}
                    </button>
                  )
                })
              )}
            </div>
          </div>
        )}

        {/* 3. Args */}
        {selectedCmd && (
          <div>
            {txArgs.length > 0 ? (
              <>
                <div className="text-[11px] font-medium mb-1" style={{ color: colors.dim }}>Arguments</div>
                <div className="grid grid-cols-2 gap-x-2 gap-y-1.5">
                  {txArgs.map((arg, i) => (
                    <div key={arg.name} className="space-y-0.5">
                      <div className="flex items-baseline gap-1">
                        <span className="text-[11px]" style={{ color: colors.dim }}>{arg.name}</span>
                        <span className="text-[11px]" style={{ color: colors.sep }}>{arg.type}</span>
                      </div>
                      <input
                        ref={i === 0 ? firstArgRef : undefined}
                        className={inputCls}
                        style={{ color: colors.value }}
                        value={argValues[arg.name] ?? ''}
                        onChange={(e) => setArgValues(prev => ({ ...prev, [arg.name]: e.target.value }))}
                        onKeyDown={(e) => { if (e.key === 'Enter') handleQueue() }}
                        placeholder={arg.type === 'epoch_ms' ? 'auto' : ''}
                      />
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="text-[11px]" style={{ color: colors.dim }}>No arguments</div>
            )}

            {/* Echo toggle */}
            {showEcho ? (
              <div className="flex items-center gap-2 mt-1">
                <span className="text-[11px]" style={{ color: colors.dim }}>Echo</span>
                <input
                  className={`${inputCls} !w-20`}
                  style={{ color: colors.value }}
                  value={echo}
                  onChange={(e) => setEcho(e.target.value)}
                  placeholder="NONE"
                />
                <button onClick={() => { setEcho('NONE'); setShowEcho(false) }} className="text-[11px]" style={{ color: colors.sep }}>hide</button>
              </div>
            ) : (
              <button onClick={() => setShowEcho(true)} className="text-[11px] mt-1" style={{ color: colors.sep }}>+ echo</button>
            )}
          </div>
        )}

        {/* Preview + Queue */}
        {selectedCmd && destNode && (
          <div className="flex items-center gap-2 pt-2 border-t" style={{ borderColor: colors.borderSubtle }}>
            <code className="flex-1 text-[11px] truncate" style={{ color: colors.dim }}>{preview}</code>
            <button
              onClick={handleQueue}
              className="flex items-center gap-1 px-3 py-1 rounded text-xs font-medium shrink-0 btn-feedback"
              style={{ color: colors.bgApp, backgroundColor: colors.label }}
            >
              <CornerDownLeft className="size-3" />
              Queue
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
