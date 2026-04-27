import { Gauge } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { PluginPageDef } from '@/plugins/registry'

export type NavigationTabDef =
  | {
      kind: 'dashboard'
      id: '__dashboard__'
      name: string
      description: string
      icon: LucideIcon
      category: 'mission'
      order: number
    }
  | {
      kind: 'plugin'
      id: string
      name: string
      description: string
      icon: LucideIcon
      category: 'mission' | 'platform'
      order?: number
      plugin: PluginPageDef
    }

export const DASHBOARD_TAB: NavigationTabDef = {
  kind: 'dashboard',
  id: '__dashboard__',
  name: 'Dashboard',
  description: 'RX / TX mission console',
  icon: Gauge,
  category: 'mission',
  order: -Infinity,
}

/** Sort: mission group first, then platform. Within each group: order ascending, then alphabetical. */
export function navTabCompare(a: NavigationTabDef, b: NavigationTabDef): number {
  const catOrder = (t: NavigationTabDef) => t.category === 'mission' ? 0 : 1
  const catDiff = catOrder(a) - catOrder(b)
  if (catDiff !== 0) return catDiff
  const orderA = a.order ?? Infinity
  const orderB = b.order ?? Infinity
  if (orderA !== orderB) return orderA - orderB
  return a.name.localeCompare(b.name)
}

/** Build NavigationTabDef[] from a PluginPageDef[] array. */
export function buildNavigationTabs(plugins: PluginPageDef[]): NavigationTabDef[] {
  const pluginNavs: NavigationTabDef[] = plugins.map(p => ({
    kind: 'plugin' as const,
    id: p.id,
    name: p.name,
    description: p.description,
    icon: p.icon,
    category: p.category,
    order: p.order,
    plugin: p,
  }))
  return [DASHBOARD_TAB, ...pluginNavs].sort(navTabCompare)
}
