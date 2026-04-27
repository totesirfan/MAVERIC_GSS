import { ExternalLink, SlidersHorizontal, Download } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { TogglePill } from '@/components/shared/atoms/TogglePill'
import { StatusDot } from '@/components/shared/atoms/StatusDot'
import { BlackoutPill } from './BlackoutPill'
import { useRxDisplayToggles } from '@/state/rxHooks'
import { colors } from '@/lib/colors'
import type { GssConfig, RxPacket, RxStatus } from '@/lib/types'

function ageColor(s: number): string {
  if (s >= 210) return colors.danger
  if (s >= 180) return colors.warning
  return colors.textMuted
}

interface RxPanelHeaderProps {
  config?: GssConfig | null
  status: RxStatus
  packets: RxPacket[]
  packetStats?: { total: number; crcFailures: number; dupCount: number; hasEcho: boolean }
  replayMode?: boolean
  receiving: boolean
  blackoutUntil?: number | null
  missionName: string
}

export function RxPanelHeader({
  config, status, packets, packetStats, replayMode, receiving, blackoutUntil, missionName,
}: RxPanelHeaderProps) {
  const { showHex, showFrame, showWrapper, hideUplink, toggleHex, toggleFrame, toggleWrapper, toggleUplink } = useRxDisplayToggles()

  return (
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
          {config?.mission.config.rx_title ?? 'RX Downlink'}
        </span>
        <StatusDot status={replayMode ? 'REPLAY' : status.zmq} />
        {replayMode ? (
          <span className="text-[11px] font-medium" style={{ color: colors.warning }}>REPLAY</span>
        ) : receiving ? (
          <span className="text-[11px] font-bold animate-pulse-text flex items-center gap-1" style={{ color: colors.success }}>
            <Download className="size-3" />
            Received
          </span>
        ) : (
          <span className="text-[11px] font-light" style={{ color: colors.textMuted }}>
            Idle — last packet{' '}
            <span className="tabular-nums" style={{ color: ageColor(status.silence_s) }}>
              {status.silence_s.toFixed(0)}s ago
            </span>
          </span>
        )}
        <BlackoutPill
          until={blackoutUntil ?? null}
          configuredMs={config?.platform.rx.tx_blackout_ms ?? 0}
        />
        {!replayMode && packets.length > 0 && (
          <span className="text-[11px] font-mono tabular-nums flex items-center gap-2 ml-auto mr-2" style={{ color: colors.textMuted }}>
            {packetStats?.total ?? packets.length} pkts
            {(packetStats?.crcFailures ?? 0) > 0 && (
              <span style={{ color: `${colors.danger}99` }}>{packetStats?.crcFailures ?? 0} CRC</span>
            )}
            {(packetStats?.dupCount ?? 0) > 0 && (
              <span style={{ color: `${colors.warning}99` }}>{packetStats?.dupCount ?? 0} dup</span>
            )}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1 group/toggles">
        <div className="flex items-center gap-1">
          <div className={`flex items-center gap-1 ${!showHex ? 'hidden group-hover/toggles:flex' : 'flex'}`}>
            <TogglePill label="HEX" active={showHex} onClick={toggleHex} />
          </div>
          <div className={`flex items-center gap-1 ${hideUplink ? 'hidden group-hover/toggles:flex' : 'flex'}`}>
            <TogglePill label="UL" active={!hideUplink} onClick={toggleUplink} />
          </div>
          <div className={`flex items-center gap-1 ${!showFrame ? 'hidden group-hover/toggles:flex' : 'flex'}`}>
            <TogglePill label="FRAME" active={showFrame} onClick={toggleFrame} />
          </div>
          <div className={`flex items-center gap-1 ${!showWrapper ? 'hidden group-hover/toggles:flex' : 'flex'}`}>
            <TogglePill label="WRAP" active={showWrapper} onClick={toggleWrapper} />
          </div>
        </div>
        {!showHex && hideUplink && !showFrame && !showWrapper && (
          <SlidersHorizontal className="size-3.5 group-hover/toggles:hidden" style={{ color: colors.dim }} />
        )}
        <Button
          variant="ghost"
          size="icon"
          className="size-6"
          onClick={() => window.open('/?panel=rx', `${missionName.toLowerCase().replace(/[^a-z0-9]+/g, '-')}-rx`, 'popup=1,width=900,height=800')}
          title={`Pop out ${missionName} RX panel`}
        >
          <ExternalLink className="size-3.5" style={{ color: colors.dim }} />
        </Button>
      </div>
    </div>
  )
}
