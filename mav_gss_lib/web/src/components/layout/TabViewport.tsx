import { Suspense, useRef, type ReactNode } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { TabActiveProvider } from '@/components/layout/TabActiveContext'
import { colors } from '@/lib/colors'
import type { PluginPageDef } from '@/plugins/registry'

interface TabViewportProps {
  plugins: PluginPageDef[]
  activeId: string
  renderDashboard: () => ReactNode
}

export function TabViewport({ plugins, activeId, renderDashboard }: TabViewportProps) {
  const mountedIdsRef = useRef<Set<string>>(new Set<string>())

  const dashboardActive = activeId === '__dashboard__'
  const knownIds = new Set(plugins.map(p => p.id))
  const isKnownPage = dashboardActive || knownIds.has(activeId)

  // Track keep-alive plugins that have been activated
  if (!dashboardActive && isKnownPage) {
    const plugin = plugins.find(p => p.id === activeId)
    if (plugin?.keepAlive) mountedIdsRef.current.add(plugin.id)
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Dashboard: always mounted, hidden when inactive */}
      <TabActiveProvider value={dashboardActive}>
        <div hidden={!dashboardActive} className="flex-1 min-h-0 flex flex-col">
          {renderDashboard()}
        </div>
      </TabActiveProvider>

      {/* Plugins: active one or any keep-alive that's been visited */}
      {plugins.map(p => {
        const isActive = activeId === p.id
        const keepMounted = p.keepAlive && mountedIdsRef.current.has(p.id)
        if (!isActive && !keepMounted) return null
        return (
          <TabActiveProvider key={p.id} value={isActive}>
            <div hidden={!isActive} className="flex-1 min-h-0 flex flex-col">
              <Suspense fallback={
                <div className="flex-1 flex items-center justify-center">
                  <Skeleton className="h-8 w-48" />
                </div>
              }>
                <p.component />
              </Suspense>
            </div>
          </TabActiveProvider>
        )
      })}

      {/* Unknown ?page= — show a not-found message */}
      {!isKnownPage && (
        <div className="flex-1 flex items-center justify-center">
          <span className="text-[11px]" style={{ color: colors.textMuted }}>
            Plugin not found
          </span>
        </div>
      )}
    </div>
  )
}
