import { Badge } from '@/components/ui/badge'
import { Shield } from 'lucide-react'
import { colors } from '@/lib/colors'
import type { DetailBlock, IntegrityBlock as IntegrityBlockType } from '@/lib/types'

function Field({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap">
      <span style={{ color: colors.sep }}>{label}:</span>
      <span style={{ color: color ?? colors.value }}>{value}</span>
    </span>
  )
}

export function SemanticBlocks({ blocks }: { blocks: DetailBlock[] }) {
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
                <Field key={fi} label={f.name} value={f.value} color={colors.label} />
              ))}
            </div>
          )}
        </div>
      ))}
    </>
  )
}

export function ProtocolBlocks({ blocks }: { blocks: DetailBlock[] }) {
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

export function IntegritySection({ blocks }: { blocks: IntegrityBlockType[] }) {
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
