import { useState, useEffect, useMemo, useRef } from 'react'
import { CornerDownLeft, ShieldCheck, Search } from 'lucide-react'
import { colors } from '@/lib/colors'
import { Command, CommandList, CommandEmpty, CommandItem } from '@/components/ui/command'
import { Command as CommandPrimitive } from 'cmdk'
import { Switch } from '@/components/ui/switch'
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
  const cmdkSearchRef = useRef<HTMLInputElement>(null)
  const hasInitialFocused = useRef(false)

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

  // Focus cmdk search when picker first becomes available
  useEffect(() => {
    if (destNode && !hasInitialFocused.current) {
      hasInitialFocused.current = true
      setTimeout(() => cmdkSearchRef.current?.focus(), 0)
    }
  }, [destNode])

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

  const dataFilteredCmds = useMemo(() => {
    if (!schema) return []
    let entries = Object.entries(schema).filter(([, def]) => !def.rx_only)
    if (destNode) {
      entries = entries.filter(([, def]) => !def.nodes || def.nodes.length === 0 || def.nodes.includes(destNode))
    }
    return entries
  }, [schema, destNode])

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
    setShowEcho(false)
    const def = schema?.[name]
    setEcho(def?.echo ?? 'NONE')
    setSearch('')
    if (def?.tx_args && def.tx_args.length > 0) {
      setTimeout(() => firstArgRef.current?.focus(), 50)
    }
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
    setShowEcho(false)
    setSearch('')
    setTimeout(() => cmdkSearchRef.current?.focus(), 50)
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
    ? `${destNode} ${selectedCmd} ${previewArgs.join(' ')}`.trim()
    : ''

  return (
    <div
      className="flex flex-col h-full"
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
      {/* Scrollable content */}
      <div className="flex-1 min-h-0 overflow-y-auto p-2.5 space-y-2.5">
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

        {/* Command picker */}
        {destNode && (
          <Command
            className="!bg-transparent !p-0 !rounded-md !overflow-visible !h-auto !size-auto [&_*]:!ring-0 [&_*]:!outline-none"
            shouldFilter={true}
          >
            {/* Search input */}
            <div
              className="flex items-center gap-2 rounded-t-md"
              style={{
                background: colors.bgBase,
                border: `1px solid ${colors.borderSubtle}`,
                borderBottom: `1px solid ${colors.borderSubtle}`,
                borderRadius: '6px 6px 0 0',
              }}
            >
              <Search className="size-[13px] ml-2.5 shrink-0" style={{ color: colors.dim }} />
              <CommandPrimitive.Input
                ref={cmdkSearchRef}
                value={search}
                onValueChange={setSearch}
                placeholder="Search commands..."
                className="flex-1 h-8 bg-transparent text-[11px] font-sans outline-none ring-0 focus:ring-0 focus:outline-none placeholder:text-[#777]"
                style={{ color: colors.value }}
              />
            </div>
            <CommandList
              className="!max-h-28 !min-h-28 !overflow-y-auto rounded-b-md"
              style={{ border: `1px solid ${colors.borderSubtle}`, borderTop: 'none' }}
            >
              <CommandEmpty>
                <span className="text-[11px]" style={{ color: colors.dim }}>No commands</span>
              </CommandEmpty>
              {dataFilteredCmds.map(([name, def]) => {
                const picked = selectedCmd === name
                return (
                  <CommandItem
                    key={name}
                    value={name}
                    onSelect={() => pickCmd(name)}
                    className="!px-2.5 !py-1.5 !rounded-none !text-xs !gap-1.5 !bg-transparent data-[selected=true]:!bg-white/[0.03]"
                    style={{
                      borderLeft: picked ? `2px solid ${colors.active}` : '2px solid transparent',
                      fontFamily: "'JetBrains Mono', monospace",
                      background: picked ? 'rgba(48,200,224,0.06)' : undefined,
                    }}
                  >
                    <span className="flex-1 flex items-center gap-1.5 min-w-0">
                      <span className="font-medium truncate" style={{ color: picked ? colors.active : colors.value }}>{name}</span>
                      {def.guard && (
                        <ShieldCheck className="size-[13px] shrink-0" style={{ color: colors.warning, opacity: 0.5 }} />
                      )}
                    </span>
                    <span className="text-[10px] shrink-0" style={{ color: colors.sep, fontFamily: 'Inter, sans-serif' }}>
                      {(def.tx_args?.length ?? 0)} arg{(def.tx_args?.length ?? 0) !== 1 ? 's' : ''}
                    </span>
                  </CommandItem>
                )
              })}
            </CommandList>
          </Command>
        )}

        {/* Args */}
        {selectedCmd && (
          <div>
            {txArgs.length > 0 ? (
              <div className="grid grid-cols-2 gap-x-2 gap-y-2">
                {txArgs.map((arg, i) => {
                  const earlierFilled = txArgs
                    .slice(0, i)
                    .every(a => (argValues[a.name] ?? '').trim() !== '')
                  const disabled = !!arg.optional && !earlierFilled
                  return (
                    <div key={arg.name} className="space-y-1" style={{ opacity: disabled ? 0.35 : 1 }}>
                      <div className="flex items-baseline gap-1">
                        <span className="text-[11px] font-medium" style={{ color: colors.dim }}>{arg.name}</span>
                        {arg.optional && (
                          <span className="text-[10px]" style={{ color: colors.sep }}>optional</span>
                        )}
                      </div>
                      <GssInput
                        ref={i === 0 ? firstArgRef : undefined}
                        className="w-full"
                        style={arg.optional ? { borderStyle: 'dashed' } : undefined}
                        value={argValues[arg.name] ?? ''}
                        disabled={disabled}
                        onChange={(e) => {
                          const next = e.target.value
                          setArgValues(prev => {
                            const updated: Record<string, string> = { ...prev, [arg.name]: next }
                            if (arg.optional && !next.trim()) {
                              for (let j = i + 1; j < txArgs.length; j++) {
                                if (txArgs[j].optional) updated[txArgs[j].name] = ''
                              }
                            }
                            return updated
                          })
                        }}
                        onKeyDown={(e) => { if (e.key === 'Enter') handleQueue() }}
                        placeholder={arg.type}
                      />
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="text-[11px]" style={{ color: colors.dim }}>No arguments</div>
            )}
          </div>
        )}

        {/* Echo switch */}
        {selectedCmd && (
          <div className="flex items-center gap-2">
            <Switch
              size="sm"
              checked={showEcho}
              onCheckedChange={(checked: boolean) => {
                setShowEcho(checked)
                if (checked) setTimeout(() => document.querySelector<HTMLInputElement>('[data-echo-input]')?.focus(), 50)
              }}
            />
            <span className="text-[11px] font-medium" style={{ color: colors.dim }}>Echo</span>
            {showEcho && (
              <GssInput
                data-echo-input
                className="!w-[72px]"
                value={echo}
                onChange={(e) => setEcho(e.target.value)}
                placeholder="NONE"
              />
            )}
          </div>
        )}
      </div>

      {/* Preview bar — static, outside scroll area */}
      {selectedCmd && destNode && (
        <div
          className="shrink-0 flex items-center gap-2 px-2.5 py-2"
          style={{ background: colors.bgPanelRaised, borderTop: `1px solid ${colors.borderSubtle}` }}
        >
          <span className="font-mono text-xs select-none" style={{ color: colors.sep }} aria-hidden="true">❯</span>
          <code className="flex-1 text-[11px] font-mono truncate" style={{ color: colors.value }}>{preview}</code>
          <button
            onClick={handleQueue}
            className="flex items-center gap-1.5 shrink-0 transition-all duration-150 btn-feedback"
            style={{
              padding: '6px 16px',
              borderRadius: '6px',
              border: `1px solid ${colors.active}`,
              backgroundColor: 'rgba(48,200,224,0.08)',
              color: colors.active,
              fontSize: '11px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <CornerDownLeft className="size-3" />
            Queue
          </button>
        </div>
      )}
    </div>
  )
}
