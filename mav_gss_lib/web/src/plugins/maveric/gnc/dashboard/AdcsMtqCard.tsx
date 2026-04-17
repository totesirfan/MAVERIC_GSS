import { Card } from './Card'
import { FieldDisplay } from '../shared/FieldDisplay'
import { fmtVec3, fmtTempC, fmtDateDisplay } from './format'
import type { GncState, StatBitfield, TimeBCD, DateBCD, AdcsTmp } from '../types'
import { colors } from '@/lib/colors'

interface AdcsMtqCardProps {
  state: GncState
  nowMs: number
}

export function AdcsMtqCard({ state, nowMs }: AdcsMtqCardProps) {
  const stat = state.STAT
  const time = state.TIME
  const date = state.DATE
  const attErr = state.ATT_ERROR
  const rate = state.RATE
  const tmp = state.ADCS_TMP
  const mtqUser = state.MTQ_USER

  const statV = stat?.value as StatBitfield | undefined
  const timeV = time?.value as TimeBCD | undefined
  const dateV = date?.value as DateBCD | undefined
  const tmpV = tmp?.value as AdcsTmp | undefined

  const modeChip = statV ? (
    <div
      className="font-mono text-[10px] px-2 py-0.5 rounded-sm"
      style={{
        color: colors.active,
        backgroundColor: colors.activeFill,
        border: `1px solid ${colors.active}4D`,
      }}
    >
      {statV.MODE_NAME}
    </div>
  ) : null

  return (
    <Card title="ADCS-MTQ" status={modeChip}>
      <FieldDisplay
        label="Mode"
        value={statV?.MODE_NAME ?? '—'}
        receivedAt={stat?.received_at_ms}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Time"
        value={timeV?.display ?? '—'}
        receivedAt={time?.received_at_ms}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Date"
        value={fmtDateDisplay(dateV)}
        receivedAt={date?.received_at_ms}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Attitude Error"
        value={fmtVec3(attErr?.value as number[] | undefined)}
        receivedAt={attErr?.received_at_ms}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Rate Error"
        value={fmtVec3(rate?.value as number[] | undefined)}
        receivedAt={rate?.received_at_ms}
        nowMs={nowMs}
      />
      <FieldDisplay
        label="Temperature"
        value={fmtTempC(tmpV)}
        receivedAt={tmp?.received_at_ms}
        nowMs={nowMs}
        forceTone={tmpV?.comm_fault ? 'danger' : undefined}
      />
      <FieldDisplay
        label="MTQ_User"
        value={fmtVec3(mtqUser?.value as number[] | undefined)}
        receivedAt={mtqUser?.received_at_ms}
        nowMs={nowMs}
      />
    </Card>
  )
}
