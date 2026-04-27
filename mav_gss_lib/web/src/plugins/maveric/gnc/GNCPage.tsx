import { useEffect, useMemo, useRef, useState } from 'react'
import { useParameterGroup } from '@/state/parametersHooks'
import { GncPlannerCard } from './dashboard/GncPlannerCard'
import { AdcsMtqCard } from './dashboard/AdcsMtqCard'
import { NaviGuiderCard } from './dashboard/NaviGuiderCard'
import { FlagsStrip } from './dashboard/FlagsStrip'
import { RegistersTable } from './registers/RegistersTable'
import type { CatalogEntry, GncState, RegisterValue } from './types'
import { useTabActive } from '@/components/layout/TabActiveContext'
import { colors } from '@/lib/colors'

type TabId = 'dashboard' | 'registers'

const TABS: Array<{ id: TabId; label: string }> = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'registers', label: 'Registers' },
]

// Starting width for the first layout pass. The dashboard then adapts
// its composition width to the container aspect each frame so uniform
// scale fills both axes with no horizontal gap or vertical clipping.
const DASH_INITIAL_WIDTH = 1440

function readTabFromUrl(): TabId {
  const t = new URLSearchParams(window.location.search).get('tab')
  return t === 'registers' ? 'registers' : 'dashboard'
}

/** MAVERIC GNC plugin page.
 *
 *  Dashboard tab (default): distilled card view per the GNC team mockup.
 *  Registers tab: full catalog table (all 49 registers) with live values
 *                 overlaid from the same snapshot cache.
 */
export default function GNCPage() {
  const { byKey, specs, lastUpdateAt } = useParameterGroup('gnc')

  // Project the parameter group into the legacy {value, t} shape the
  // dashboard cards already consume. This keeps each card's component
  // signature stable while the underlying state moves to the platform
  // ParametersProvider.
  const state = useMemo<GncState>(() => {
    const out: GncState = {}
    for (const [key, entry] of Object.entries(byKey)) {
      out[key] = { value: entry.v as RegisterValue, t: entry.t }
    }
    return out
  }, [byKey])

  // Project parameter specs into the legacy CatalogEntry[] shape the
  // RegistersTable consumes. tags.module / tags.register identify
  // addressable spacecraft registers; keys without tags get null on
  // both, so the table's `module !== null` filter still hides
  // non-register canonical keys.
  const catalog = useMemo<CatalogEntry[]>(() => specs.map((s) => ({
    module:   typeof s.tags?.module === 'number'   ? s.tags.module   : null,
    register: typeof s.tags?.register === 'number' ? s.tags.register : null,
    name:     s.key,
    type:     s.type,
    unit:     s.unit,
    notes:    s.description,
  })), [specs])

  const tabActive = useTabActive()
  const [tab, setTab] = useState<TabId>(readTabFromUrl)

  // Sync tab with URL when navigation happens elsewhere (palette, browser back/forward)
  useEffect(() => {
    const sync = () => setTab(readTabFromUrl())
    window.addEventListener('gss:nav', sync)
    window.addEventListener('popstate', sync)
    return () => {
      window.removeEventListener('gss:nav', sync)
      window.removeEventListener('popstate', sync)
    }
  }, [])

  // When user clicks an in-page tab, keep the URL in sync so a reload restores the same view
  const selectTab = (next: TabId) => {
    setTab(next)
    const url = new URL(window.location.href)
    if (next === 'dashboard') url.searchParams.delete('tab')
    else url.searchParams.set('tab', next)
    window.history.replaceState({}, '', url.toString())
  }

  // Aspect-adaptive fit-to-window for the dashboard tab.
  // Each pass: measure natural content height at current layout width,
  // then solve for (nominalWidth, scale) so that
  //   scale × nominalWidth = containerWidth
  //   scale × naturalHeight = containerHeight
  // i.e. scale = ch/nh and nominalWidth = cw × nh/ch. The grid reflows at
  // that width; card heights usually shift by a few pixels as columns
  // widen/narrow, so epsilons guard against ResizeObserver oscillation.
  const dashContainerRef = useRef<HTMLDivElement>(null)
  const dashContentRef = useRef<HTMLDivElement>(null)
  const [dashScale, setDashScale] = useState(1)
  const [dashNominalWidth, setDashNominalWidth] = useState(DASH_INITIAL_WIDTH)

  useEffect(() => {
    if (tab !== 'dashboard' || !tabActive) return
    const container = dashContainerRef.current
    const content = dashContentRef.current
    if (!container || !content) return
    let frame = 0
    const update = () => {
      frame = 0
      const cw = container.clientWidth
      const ch = container.clientHeight
      const nh = content.offsetHeight
      if (nh === 0 || cw === 0 || ch === 0) return
      const targetWidth = Math.round(cw * nh / ch)
      const targetScale = ch / nh
      setDashNominalWidth(prev => Math.abs(prev - targetWidth) > 1 ? targetWidth : prev)
      setDashScale(prev => Math.abs(prev - targetScale) > 0.005 ? targetScale : prev)
    }
    const scheduleUpdate = () => {
      if (frame !== 0) return
      frame = requestAnimationFrame(update)
    }
    update()
    const ro = new ResizeObserver(scheduleUpdate)
    ro.observe(container)
    ro.observe(content)
    return () => {
      ro.disconnect()
      if (frame !== 0) cancelAnimationFrame(frame)
    }
  }, [tab, tabActive])

  // Shared "now" tick so all age chips in one render share a timebase.
  // Pauses when the tab is backgrounded to avoid burning render cycles.
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    let id: ReturnType<typeof setInterval> | null = null
    const start = () => {
      if (id !== null || !tabActive) return
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
  }, [tabActive])

  return (
    <div className="h-full w-full flex flex-col bg-[#080808] text-[#E5E5E5]">
      {/* Tab bar */}
      <div className="flex items-center gap-1 px-3 pt-2 pb-0 border-b border-[#1a1a1a]">
        {TABS.map((t) => {
          const active = t.id === tab
          return (
            <button
              key={t.id}
              onClick={() => selectTab(t.id)}
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
          <div
            ref={dashContainerRef}
            className="h-full w-full overflow-hidden"
          >
            <div
              ref={dashContentRef}
              className="p-3"
              style={{
                width: dashNominalWidth,
                transform: `scale(${dashScale})`,
                transformOrigin: 'top left',
              }}
            >
              <div className="grid grid-cols-3 gap-3 mb-3">
                <div className="flex flex-col gap-3 min-w-0">
                  <GncPlannerCard state={state} nowMs={nowMs} />
                  <NaviGuiderCard state={state} nowMs={nowMs} />
                </div>
                <div className="col-span-2 min-w-0">
                  <AdcsMtqCard state={state} nowMs={nowMs} />
                </div>
              </div>
              <FlagsStrip state={state} nowMs={nowMs} />
            </div>
          </div>
        ) : (
          <RegistersTable catalog={catalog} state={state} nowMs={nowMs} />
        )}
      </div>
    </div>
  )
}
