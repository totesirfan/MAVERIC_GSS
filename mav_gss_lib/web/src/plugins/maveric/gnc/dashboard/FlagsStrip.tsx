import { FlagDot } from '../shared/FlagDot'
import { colors } from '@/lib/colors'
import type { GncState, StatBitfield, ActErrBitfield, SenErrBitfield } from '../types'

interface FlagsStripProps {
  state: GncState
  nowMs: number
}

export function FlagsStrip({ state, nowMs }: FlagsStripProps) {
  // state.STAT is the STAT register (module 0, reg 128). Both the RES
  // path (mtq_get_1 / mtq_get_fast) and tlm_beacon populate it; the
  // platform router LWW-merges them, so this consumer sees the newest
  // value regardless of source.
  const stat = state.STAT
  const actErr = state.ACT_ERR
  const senErr = state.SEN_ERR

  const statV = stat?.value as StatBitfield | undefined
  const actV  = actErr?.value as ActErrBitfield | undefined
  const senV  = senErr?.value as SenErrBitfield | undefined

  const statAt = stat?.t ?? null
  const actAt  = actErr?.t ?? null
  const senAt  = senErr?.t ?? null

  return (
    <div
      className="border rounded-sm"
      style={{ backgroundColor: colors.bgPanel, borderColor: colors.borderSubtle }}
    >
      <div
        className="px-3 py-2 border-b"
        style={{ borderColor: colors.borderSubtle }}
      >
        <h3
          className="font-sans text-[12px] uppercase tracking-wider"
          style={{ color: colors.textPrimary }}
        >
          ADCS · MTQ Flags
        </h3>
      </div>

      {/* Row 1 — STAT byte[3]: error & protection flags */}
      <div className="grid grid-cols-7 border-b border-[#1a1a1a]">
        <FlagDot label="Hard Error"  value={statV?.HERR}            receivedAtMs={statAt} nowMs={nowMs} />
        <FlagDot label="Soft Error"  value={statV?.SERR}            receivedAtMs={statAt} nowMs={nowMs} />
        <FlagDot label="Watchdog"    value={statV?.WDT}             receivedAtMs={statAt} nowMs={nowMs} />
        <FlagDot label="Undervolt"   value={statV?.UV}              receivedAtMs={statAt} nowMs={nowMs} />
        <FlagDot label="Overcurrent" value={statV?.OC}              receivedAtMs={statAt} nowMs={nowMs} />
        <FlagDot label="Temp Prot"   value={statV?.OT}              receivedAtMs={statAt} nowMs={nowMs} />
        <FlagDot label="GNSS"        value={statV?.GNSS_UP_TO_DATE} receivedAtMs={statAt} nowMs={nowMs} polarity="status" />
      </div>

      {/* Row 2 — STAT byte[1]: status flags + EKF */}
      <div className="grid grid-cols-8 border-b border-[#1a1a1a]">
        <FlagDot label="TLE"         value={statV?.TLE}   receivedAtMs={statAt} nowMs={nowMs} polarity="status" />
        <FlagDot label="De-Sat"      value={statV?.DES}   receivedAtMs={statAt} nowMs={nowMs} polarity="status" />
        <FlagDot label="Sun"         value={statV?.SUN}   receivedAtMs={statAt} nowMs={nowMs} polarity="status" />
        <FlagDot label="Target Lost" value={statV?.TGL}   receivedAtMs={statAt} nowMs={nowMs} />
        <FlagDot label="Tumble"      value={statV?.TUMB}  receivedAtMs={statAt} nowMs={nowMs} />
        <FlagDot label="Ang Mom"     value={statV?.AME}   receivedAtMs={statAt} nowMs={nowMs} />
        <FlagDot label="Custom SV"   value={statV?.CUSSV} receivedAtMs={statAt} nowMs={nowMs} polarity="status" />
        <FlagDot label="EKF"         value={statV?.EKF}   receivedAtMs={statAt} nowMs={nowMs} polarity="status" />
      </div>

      {/* Row 3 — ACT_ERR (MTQ0-2) + SEN_ERR (IMU0-1, MAG5, FSS5) */}
      <div className="grid grid-cols-7">
        <FlagDot label="MTQ2" value={actV?.MTQ2} receivedAtMs={actAt} nowMs={nowMs} />
        <FlagDot label="MTQ1" value={actV?.MTQ1} receivedAtMs={actAt} nowMs={nowMs} />
        <FlagDot label="MTQ0" value={actV?.MTQ0} receivedAtMs={actAt} nowMs={nowMs} />
        <FlagDot label="IMU1" value={senV?.IMU1} receivedAtMs={senAt} nowMs={nowMs} />
        <FlagDot label="IMU0" value={senV?.IMU0} receivedAtMs={senAt} nowMs={nowMs} />
        <FlagDot label="MAG5" value={senV?.MAG5} receivedAtMs={senAt} nowMs={nowMs} />
        <FlagDot label="FSS5" value={senV?.FSS5} receivedAtMs={senAt} nowMs={nowMs} />
      </div>
    </div>
  )
}
