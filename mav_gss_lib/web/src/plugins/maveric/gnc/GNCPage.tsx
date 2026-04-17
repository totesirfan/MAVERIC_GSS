import { useEffect, useState } from 'react'
import { useGncRegisters } from './useGncRegisters'
import { GncPlannerCard } from './dashboard/GncPlannerCard'
import { AdcsMtqCard } from './dashboard/AdcsMtqCard'
import { NaviGuiderCard } from './dashboard/NaviGuiderCard'
import { FlagsStrip } from './dashboard/FlagsStrip'
import { RegistersTable } from './registers/RegistersTable'
import { useRegisterCatalog } from './registers/useRegisterCatalog'
import { colors } from '@/lib/colors'

type TabId = 'dashboard' | 'registers'

const TABS: Array<{ id: TabId; label: string }> = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'registers', label: 'Registers' },
]

/** MAVERIC GNC plugin page.
 *
 *  Dashboard tab (default): distilled card view per the GNC team mockup.
 *  Registers tab: full catalog table (all 49 registers) with live values
 *                 overlaid from the same snapshot cache.
 */
export default function GNCPage() {
  const { state, lastUpdateAt } = useGncRegisters()
  const catalog = useRegisterCatalog()
  const [tab, setTab] = useState<TabId>('dashboard')

  // Shared "now" tick so all age chips in one render share a timebase.
  // Pauses when the tab is backgrounded to avoid burning render cycles.
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    let id: ReturnType<typeof setInterval> | null = null
    const start = () => {
      if (id !== null) return
      setNowMs(Date.now())
      id = setInterval(() => setNowMs(Date.now()), 1000)
    }
    const stop = () => {
      if (id !== null) { clearInterval(id); id = null }
    }
    if (document.visibilityState === 'visible') start()
    const onVis = () => (document.visibilityState === 'visible' ? start() : stop())
    document.addEventListener('visibilitychange', onVis)
    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [])

  return (
    <div className="h-full w-full flex flex-col bg-[#080808] text-[#E5E5E5]">
      {/* Tab bar */}
      <div className="flex items-center gap-1 px-3 pt-2 pb-0 border-b border-[#1a1a1a]">
        {TABS.map((t) => {
          const active = t.id === tab
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className="font-sans text-[11px] uppercase tracking-wider px-3 py-1.5 border border-b-0 rounded-t-sm transition-colors"
              style={{
                backgroundColor: active ? '#0E0E0E' : 'transparent',
                color:           active ? colors.textPrimary : colors.textMuted,
                borderColor:     active ? '#222' : 'transparent',
              }}
            >
              {t.label}
            </button>
          )
        })}
        <div className="flex-1" />
        <div className="font-mono text-[11px] text-[#555]">
          {lastUpdateAt
            ? `Last update ${new Date(lastUpdateAt).toLocaleTimeString()}`
            : 'Awaiting GNC telemetry…'}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {tab === 'dashboard' ? (
          <div className="h-full overflow-auto p-3">
            <div className="grid grid-cols-3 gap-3 mb-3">
              <GncPlannerCard state={state} nowMs={nowMs} />
              <AdcsMtqCard state={state} nowMs={nowMs} />
              <NaviGuiderCard state={state} nowMs={nowMs} />
            </div>
            <FlagsStrip state={state} nowMs={nowMs} />
          </div>
        ) : (
          <RegistersTable catalog={catalog} state={state} nowMs={nowMs} />
        )}
      </div>
    </div>
  )
}
