import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Clock, Radio, ArrowRightLeft, Shield, AlertTriangle, Binary, Satellite } from 'lucide-react'
import { colors, ptypeColor, frameColor } from '@/lib/colors'
import { getNodeFullName } from '@/lib/nodes'
import type { DetailBlock, GssConfig, IntegrityBlock as IntegrityBlockType, RxPacket } from '@/lib/types'

interface PacketDetailProps {
  packet: RxPacket
  nodeDescriptions?: GssConfig['node_descriptions']
  showHex: boolean
  showWrapper: boolean
  showFrame: boolean
}

function F({ icon: Icon, label, value, color, tooltip }: { icon?: React.ElementType; label: string; value: string; color?: string; tooltip?: string }) {
  const valueEl = <span style={{ color: color ?? colors.value }}>{value}</span>
  return (
    <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap">
      {Icon && <Icon className="size-3" style={{ color: colors.sep }} />}
      <span style={{ color: colors.sep }}>{label}:</span>
      {tooltip ? (
        <TooltipProvider delay={300}>
          <Tooltip>
            <TooltipTrigger render={<span />} style={{ color: color ?? colors.value }}>{value}</TooltipTrigger>
            <TooltipContent side="top" className="text-xs">{tooltip}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      ) : valueEl}
    </span>
  )
}

const hasEcho = (echo: string) => echo && echo !== 'NONE' && echo !== '0' && echo !== ''

function SemanticBlocks({ blocks }: { blocks: DetailBlock[] }) {
  return (
    <>
      {blocks.map((block, bi) => (
        <div key={bi}>
          {block.label && block.kind !== 'time' && (
            <span className="text-[11px] font-medium mr-2" style={{ color: colors.sep }}>{block.label}</span>
          )}
          {block.kind === 'args' ? (
            <div className="space-y-0.5">
              {block.fields.map((f, fi) => (
                <div key={fi} className="flex items-center gap-2 text-xs pl-4">
                  <span style={{ color: colors.label }}>{f.name}</span>
                  <span style={{ color: colors.sep }}>=</span>
                  <span style={{ color: colors.value }}>{f.value}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-4">
              {block.fields.map((f, fi) => (
                <F key={fi} label={f.name} value={f.value} color={colors.label} />
              ))}
            </div>
          )}
        </div>
      ))}
    </>
  )
}

function ProtocolBlocks({ blocks }: { blocks: DetailBlock[] }) {
  return (
    <>
      {blocks.map((block, bi) => (
        <div key={bi} className="text-xs whitespace-nowrap overflow-x-auto">
          <span className="font-medium mr-2" style={{ color: colors.sep }}>{block.label}</span>
          {block.fields.map((f, fi) => (
            <span key={fi} className="mr-3">
              <span style={{ color: colors.dim }}>{f.name}=</span>
              <span style={{ color: colors.value }}>{f.value}</span>
            </span>
          ))}
        </div>
      ))}
    </>
  )
}

function IntegritySection({ blocks }: { blocks: IntegrityBlockType[] }) {
  return (
    <div className="flex items-center gap-2">
      <Shield className="size-3" style={{ color: colors.sep }} />
      {blocks.length === 0 ? (
        <span className="text-[11px]" style={{ color: colors.dim }}>No CRC data</span>
      ) : (
        blocks.map((b, i) => (
          <Badge key={i} variant={b.ok === false ? 'destructive' : 'secondary'} className="text-[11px] h-5">
            {b.label}: {b.ok === null ? '?' : b.ok ? 'OK' : 'FAIL'}
          </Badge>
        ))
      )}
    </div>
  )
}

export function PacketDetail({ packet: p, nodeDescriptions, showHex, showWrapper, showFrame }: PacketDetailProps) {
  const r = p._rendering

  const crc16 = p.crc16_ok === null ? null : p.crc16_ok
  const crc32 = p.crc32_ok === null ? null : p.crc32_ok

  const namedArgs = p.args_named ?? []
  const extraArgs = p.args_extra ?? []

  return (
    <div className="px-3 py-2 space-y-1.5 border-t font-mono" style={{ borderColor: colors.borderSubtle }}>
      {r ? (
        <>
          {/* Frame — only when toggle is on */}
          {showFrame && (
            <div className="flex items-center gap-4">
              <F icon={Radio} label="Frame" value={p.frame || '--'} color={frameColor(p.frame)} />
            </div>
          )}

          {/* Mission-provided semantic blocks */}
          <SemanticBlocks blocks={r.detail_blocks} />

          {/* Warnings (platform-owned) */}
          {p.warnings.length > 0 && (
            <div className="flex items-center gap-1">
              <AlertTriangle className="size-3 shrink-0" style={{ color: colors.warning }} />
              {p.warnings.map((w, i) => (
                <Badge key={i} className="text-[11px] h-5" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>
                  {w}
                </Badge>
              ))}
            </div>
          )}

          {/* Protocol + Integrity (platform-owned rendering, mission-provided data) */}
          {showWrapper && (
            <>
              <Separator style={{ backgroundColor: colors.borderSubtle }} />
              <IntegritySection blocks={r.integrity_blocks} />
              <ProtocolBlocks blocks={r.protocol_blocks} />
            </>
          )}

          {/* Raw hex (platform-owned) */}
          {showHex && p.raw_hex && (
            <>
              <Separator style={{ backgroundColor: colors.borderSubtle }} />
              <div className="flex items-start gap-1">
                <Binary className="size-3 mt-0.5 shrink-0" style={{ color: colors.sep }} />
                <pre className="text-[11px] p-2 rounded font-mono flex-1 whitespace-pre-wrap break-all" style={{ color: colors.dim, backgroundColor: colors.bgApp }}>
                  {p.raw_hex.match(/.{1,2}/g)?.join(' ')}
                </pre>
              </div>
            </>
          )}
        </>
      ) : (
        <>
          {/* Time */}
          <div className="flex items-center gap-4">
            {p.sat_time_utc ? (
              <F icon={Satellite} label="SAT TIME" value={`${p.sat_time_utc} · ${p.sat_time_local || ''}`} color={colors.value} />
            ) : (
              <F icon={Clock} label="Time" value={p.time} />
            )}
          </div>

          {/* Frame — only when toggle is on */}
          {showFrame && (
            <div className="flex items-center gap-4">
              <F icon={Radio} label="Frame" value={p.frame || '--'} color={frameColor(p.frame)} />
            </div>
          )}

          {/* Routing */}
          <div className="flex items-center gap-4">
            <F label="Src" value={p.src} color={colors.label} tooltip={getNodeFullName(p.src, nodeDescriptions)} />
            <F label="Dest" value={p.dest} color={colors.label} tooltip={getNodeFullName(p.dest, nodeDescriptions)} />
            {hasEcho(p.echo) && <F label="Echo" value={p.echo} color={colors.warning} tooltip={getNodeFullName(p.echo, nodeDescriptions)} />}
            <F label="Type" value={p.ptype} color={ptypeColor(p.ptype)} />
          </div>
          <div className="flex items-center gap-4">
            <F icon={ArrowRightLeft} label="Cmd" value={p.cmd || '--'} color={colors.value} />
          </div>

          {/* Args: named on separate rows, then extra on separate rows */}
          {(namedArgs.length > 0 || extraArgs.length > 0) && (
            <div className="space-y-0.5">
              {namedArgs.map((a, i) => (
                <div key={i} className="flex items-center gap-2 text-xs pl-4">
                  <span style={{ color: colors.label }}>{a.name}</span>
                  <span style={{ color: colors.sep }}>=</span>
                  <span style={{ color: colors.value }}>{a.value}</span>
                </div>
              ))}
              {extraArgs.map((val, i) => (
                <div key={`extra-${i}`} className="flex items-center gap-2 text-xs pl-4">
                  <span style={{ color: colors.dim }}>arg{namedArgs.length + i}</span>
                  <span style={{ color: colors.sep }}>=</span>
                  <span style={{ color: colors.value }}>{val}</span>
                </div>
              ))}
            </div>
          )}

          {/* Warnings */}
          {p.warnings.length > 0 && (
            <div className="flex items-center gap-1">
              <AlertTriangle className="size-3 shrink-0" style={{ color: colors.warning }} />
              {p.warnings.map((w, i) => (
                <Badge key={i} className="text-[11px] h-5" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>
                  {w}
                </Badge>
              ))}
            </div>
          )}

          {/* WRAP section: CRC + CSP + AX.25 */}
          {showWrapper && (
            <>
              <Separator style={{ backgroundColor: colors.borderSubtle }} />

              {/* CRC */}
              <div className="flex items-center gap-2">
                <Shield className="size-3" style={{ color: colors.sep }} />
                {crc16 !== null && (
                  <Badge variant={crc16 ? 'secondary' : 'destructive'} className="text-[11px] h-5">
                    CRC-16: {crc16 ? 'OK' : 'FAIL'}
                  </Badge>
                )}
                {crc32 !== null && (
                  <Badge variant={crc32 ? 'secondary' : 'destructive'} className="text-[11px] h-5">
                    CRC-32: {crc32 ? 'OK' : 'FAIL'}
                  </Badge>
                )}
                {crc16 === null && crc32 === null && (
                  <span className="text-[11px]" style={{ color: colors.dim }}>No CRC data</span>
                )}
              </div>

              {/* CSP header */}
              {p.csp_header && (
                <div className="text-xs whitespace-nowrap overflow-x-auto">
                  <span className="font-medium mr-2" style={{ color: colors.sep }}>CSP</span>
                  {Object.entries(p.csp_header).map(([k, v]) => (
                    <span key={k} className="mr-3">
                      <span style={{ color: colors.dim }}>{k}=</span>
                      <span style={{ color: colors.value }}>{v}</span>
                    </span>
                  ))}
                </div>
              )}

              {/* AX.25 header */}
              {p.ax25_header && (
                <div className="text-xs">
                  <span className="font-medium mr-2" style={{ color: colors.sep }}>AX.25</span>
                  <span style={{ color: colors.dim }}>{p.ax25_header}</span>
                </div>
              )}
            </>
          )}

          {/* Hex dump */}
          {showHex && p.raw_hex && (
            <>
              <Separator style={{ backgroundColor: colors.borderSubtle }} />
              <div className="flex items-start gap-1">
                <Binary className="size-3 mt-0.5 shrink-0" style={{ color: colors.sep }} />
                <pre className="text-[11px] p-2 rounded font-mono flex-1 whitespace-pre-wrap break-all" style={{ color: colors.dim, backgroundColor: colors.bgApp }}>
                  {p.raw_hex.match(/.{1,2}/g)?.join(' ')}
                </pre>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
