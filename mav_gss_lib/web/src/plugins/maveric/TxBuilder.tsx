import { useState, useEffect, useMemo, useRef } from 'react'
import { CornerDownLeft } from 'lucide-react'
import { colors } from '@/lib/colors'
import { PtypeBadge } from '@/components/shared/PtypeBadge'
import type { MissionBuilderProps } from '@/lib/types'
import { GssInput } from '@/components/ui/gss-input'

interface CommandArg {
  name: string
  type: string
  important?: boolean
  optional?: boolean
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

  // Auto-select first node so cmdk picker renders on builder open
  useEffect(() => {
    if (nodes.length > 0 && !destNode) {
      setDestNode(nodes[0].name)
    }
  }, [nodes, destNode])

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

  // Build preview args in schema order (not argValues insertion order).
  // Stop at the first missing arg so the preview matches what the
  // backend will actually put on the wire (positional, trailing-only).
  const previewArgs: string[] = []
  for (const a of txArgs) {
    const val = (argValues[a.name] ?? '').trim()
    if (!val) break
    previewArgs.push(val)
  }
  const preview = selectedCmd && destNode
    ? `${destNode} ${echo !== 'NONE' ? echo + ' ' : ''}${cmdDef?.ptype || 'CMD'} ${selectedCmd} ${previewArgs.join(' ')}`.trim()
    : ''

  return (
    <div
      className="flex flex-col overflow-y-auto h-full"
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          e.preventDefault()
          if (search) {
            setSearch('')
            e.stopPropagation()
          } else {
            onClose()
          }
        }
      }}
    >
      <div className="p-2 space-y-2">
        {/* Node rail */}
        <div
          className="flex rounded-md p-0.5 gap-0.5"
          style={{ background: colors.bgPanelRaised, border: `1px solid ${colors.borderSubtle}` }}
          role="radiogroup"
          aria-label="Destination node"
        >
          {nodes.map((n) => {
            const active = destNode === n.name
            return (
              <button
                key={n.id}
                onClick={() => pickNode(n.name)}
                role="radio"
                aria-checked={active}
                className="flex-1 text-center py-1.5 px-1 rounded text-[11px] font-semibold transition-all duration-150"
                style={{
                  background: active ? 'rgba(48,200,224,0.10)' : 'transparent',
                  color: active ? colors.active : colors.dim,
                  boxShadow: active ? '0 0 0 1px rgba(48,200,224,0.2)' : 'none',
                }}
              >
                {n.name}
              </button>
            )
          })}
        </div>

        {/* 2. Command picker */}
        {destNode && (
          <div>
            <div className="text-[11px] font-medium mb-1" style={{ color: colors.dim }}>Command</div>
            <GssInput
              autoFocus={!selectedCmd}
              type="text"
              className="w-full mb-1"
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
                  {txArgs.map((arg, i) => {
                    // Trailing-optional gate: an optional arg is only
                    // enabled when every earlier arg has a value. This
                    // prevents the operator from creating a gap that
                    // the backend would reject at send time.
                    const earlierFilled = txArgs
                      .slice(0, i)
                      .every(a => (argValues[a.name] ?? '').trim() !== '')
                    const disabled = !!arg.optional && !earlierFilled
                    return (
                      <div key={arg.name} className="space-y-0.5">
                        <div className="flex items-baseline gap-1">
                          <span className="text-[11px]" style={{ color: colors.dim }}>{arg.name}</span>
                          <span className="text-[11px]" style={{ color: colors.sep }}>{arg.type}</span>
                          {arg.optional && (
                            <span className="text-[10px] italic" style={{ color: colors.sep }}>optional</span>
                          )}
                        </div>
                        <GssInput
                          ref={i === 0 ? firstArgRef : undefined}
                          className="w-full"
                          value={argValues[arg.name] ?? ''}
                          disabled={disabled}
                          onChange={(e) => {
                            const next = e.target.value
                            setArgValues(prev => {
                              const updated: Record<string, string> = { ...prev, [arg.name]: next }
                              // Clearing an optional clears every
                              // downstream optional too, since later
                              // optionals can't remain without it.
                              if (arg.optional && !next.trim()) {
                                for (let j = i + 1; j < txArgs.length; j++) {
                                  if (txArgs[j].optional) updated[txArgs[j].name] = ''
                                }
                              }
                              return updated
                            })
                          }}
                          onKeyDown={(e) => { if (e.key === 'Enter') handleQueue() }}
                          placeholder={arg.type === 'epoch_ms' ? 'auto' : ''}
                        />
                      </div>
                    )
                  })}
                </div>
              </>
            ) : (
              <div className="text-[11px]" style={{ color: colors.dim }}>No arguments</div>
            )}

            {/* Echo toggle */}
            {showEcho ? (
              <div className="flex items-center gap-2 mt-1">
                <span className="text-[11px]" style={{ color: colors.dim }}>Echo</span>
                <GssInput
                  className="!w-20"
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
