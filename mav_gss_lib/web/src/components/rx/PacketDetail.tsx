import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Clock, Radio, AlertTriangle, Binary } from 'lucide-react'
import { colors, frameColor } from '@/lib/colors'
import { SemanticBlocks, ProtocolBlocks, IntegritySection } from '@/components/shared/rendering/RenderingBlocks'
import type { RxPacket } from '@/lib/types'

interface PacketDetailProps {
  packet: RxPacket
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

export function PacketDetail({ packet: p, showHex, showWrapper, showFrame }: PacketDetailProps) {
  const r = p._rendering

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
          {/* Minimal fallback for entries without _rendering */}
          <div className="flex items-center gap-4">
            <F icon={Clock} label="Time" value={p.time} />
          </div>

          {showFrame && p.frame && (
            <div className="flex items-center gap-4">
              <F icon={Radio} label="Frame" value={p.frame} color={frameColor(p.frame)} />
            </div>
          )}

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
