import { useCallback, useMemo, useState } from 'react'
import { Download } from 'lucide-react'
import { PacketList } from '@/components/rx/PacketList'
import { colors } from '@/lib/colors'
import type { ColumnDef, RxPacket } from '@/lib/types'

interface RxLogPanelProps {
  packets: RxPacket[]
  columns?: ColumnDef[]
  receiving: boolean
}

/** Imaging-filtered RX log — mirrors the main dashboard RxPanel visually. */
export function RxLogPanel({ packets, columns, receiving }: RxLogPanelProps) {
  const [autoScroll, setAutoScroll] = useState(true)
  const downlinkPackets = useMemo(
    () => packets.filter(p => !p.is_echo),
    [packets],
  )
  const compactColumns = useMemo(
    () => (columns ?? []).filter(c => c.id !== 'src'),
    [columns],
  )

  const lastNum = downlinkPackets.length > 0 ? downlinkPackets[downlinkPackets.length - 1].num : null
  const handleScrolledUp = useCallback(() => setAutoScroll(false), [])

  return (
    <div
      className="flex flex-col flex-1 min-h-0 rounded-lg border overflow-hidden shadow-panel"
      style={{
        borderColor: receiving ? `${colors.success}55` : colors.borderSubtle,
        backgroundColor: colors.bgPanel,
        transition: 'border-color 160ms ease',
      }}
    >
      <div
        className={`flex items-center justify-between px-3 py-1.5 border-b shrink-0 ${receiving ? 'animate-sweep-green' : ''}`}
        style={{
          borderColor: colors.borderSubtle,
          backgroundColor: receiving ? `${colors.success}08` : 'transparent',
          transition: 'background-color 160ms ease',
        }}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold tracking-wide uppercase" style={{ color: colors.value }}>
            Imaging RX Log
          </span>
          {receiving ? (
            <span className="text-[11px] font-bold animate-pulse-text flex items-center gap-1" style={{ color: colors.success }}>
              <Download className="size-3" />
              Received
            </span>
          ) : (
            <span className="text-[11px] font-light" style={{ color: colors.textMuted }}>
              Idle
            </span>
          )}
        </div>
        {downlinkPackets.length > 0 && (
          <span className="text-[11px] font-mono tabular-nums" style={{ color: colors.textMuted }}>
            {downlinkPackets.length} pkt{downlinkPackets.length === 1 ? '' : 's'}
          </span>
        )}
      </div>

      <PacketList
        packets={downlinkPackets}
        columns={compactColumns}
        showFrame={false}
        showEcho={false}
        flashPacketNum={lastNum}
        selectedNum={null}
        onSelect={() => {}}
        autoScroll={autoScroll}
        onScrolledUp={handleScrolledUp}
        compact
      />
    </div>
  )
}
