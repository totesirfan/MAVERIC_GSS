import { useEffect, useRef } from 'react'
import { FileText, Download } from 'lucide-react'
import { colors } from '@/lib/colors'

export interface ImagingLogRow {
  num: number
  time: string
  cmd: string
  args: string
}

interface RxLogPanelProps {
  packets: ImagingLogRow[]
  receiving: boolean
}

/** Compact scrolling RX log filtered to imaging commands. */
export function RxLogPanel({ packets, receiving }: RxLogPanelProps) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [packets.length])

  return (
    <div
      className="flex-1 flex flex-col rounded-lg border overflow-hidden"
      style={{
        borderColor: receiving ? `${colors.success}55` : colors.borderSubtle,
        backgroundColor: colors.bgPanel,
        transition: 'border-color 160ms ease',
      }}
    >
      <div
        className={`flex items-center gap-2 px-3 py-1.5 border-b shrink-0 ${receiving ? 'animate-sweep-green' : ''}`}
        style={{
          borderColor: colors.borderSubtle,
          backgroundColor: receiving ? `${colors.success}08` : 'transparent',
          transition: 'background-color 160ms ease',
        }}
      >
        {receiving ? (
          <Download className="size-3.5" style={{ color: colors.success }} />
        ) : (
          <FileText className="size-3.5" style={{ color: colors.dim }} />
        )}
        <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: receiving ? colors.success : colors.label }}>
          {receiving ? 'Receiving' : 'Imaging RX Log'}
        </span>
        <span className="text-[11px] ml-auto" style={{ color: colors.dim }}>{packets.length}</span>
      </div>
      <div className="flex-1 overflow-y-auto font-mono text-[11px]">
        <div
          className="flex items-center px-2 py-1 border-b sticky top-0"
          style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel, color: colors.dim }}
        >
          <span className="w-9 text-right shrink-0">#</span>
          <span className="w-[60px] ml-2 shrink-0">time</span>
          <span className="w-[120px] ml-2 shrink-0">cmd</span>
          <span className="flex-1 ml-2">args</span>
        </div>
        {packets.length === 0 ? (
          <div className="flex items-center justify-center py-8 text-[11px]" style={{ color: colors.dim }}>
            Waiting for imaging packets...
          </div>
        ) : (
          packets.map((p, i) => {
            const isLatest = i === packets.length - 1 && receiving
            return (
              <div
                key={p.num}
                className="flex items-center px-2 py-0.5 hover:bg-white/[0.02]"
                style={{
                  color: colors.value,
                  backgroundColor: isLatest ? `${colors.success}0A` : undefined,
                }}
              >
                <span className="w-9 text-right shrink-0" style={{ color: colors.dim }}>{p.num}</span>
                <span className="w-[60px] ml-2 shrink-0" style={{ color: colors.dim }}>{p.time}</span>
                <span className="w-[120px] ml-2 shrink-0">{p.cmd}</span>
                <span className="flex-1 ml-2 truncate">{p.args}</span>
              </div>
            )
          })
        )}
        <div ref={endRef} />
      </div>
    </div>
  )
}
