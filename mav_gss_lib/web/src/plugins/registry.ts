/**
 * Plugin Registry — Convention-Based Discovery
 *
 * Discovers mission plugins by convention:
 *   plugins/<mission_id>/TxBuilder.tsx   — inline TX builder (mounts in TX panel)
 *   plugins/<mission_id>/plugins.ts      — page plugin manifest
 *
 * No manual registration needed — just create the files.
 */
import { lazy, type ComponentType, type LazyExoticComponent } from 'react'
import type { MissionBuilderProps } from '@/lib/types'

// ── TX Builder Discovery ────────────────────────────────────────────

const builderModules = import.meta.glob<{ default: ComponentType<MissionBuilderProps> }>(
  './**/TxBuilder.tsx',
)

const builders: Record<string, () => Promise<{ default: ComponentType<MissionBuilderProps> }>> = {}
for (const path of Object.keys(builderModules)) {
  const match = path.match(/^\.\/([^/]+)\/TxBuilder\.tsx$/)
  if (match) {
    builders[match[1].toLowerCase()] = builderModules[path]
  }
}

const builderCache = new Map<string, ComponentType<MissionBuilderProps>>()

export function getMissionBuilder(missionId: string): ComponentType<MissionBuilderProps> | null {
  const key = missionId.toLowerCase()
  const loader = builders[key]
  if (!loader) return null
  let component = builderCache.get(key)
  if (!component) {
    component = lazy(loader)
    builderCache.set(key, component)
  }
  return component
}

// ── Page Plugin Discovery ───────────────────────────────────────────

export interface PluginPageDef {
  id: string
  name: string
  description: string
  icon: string
  component: LazyExoticComponent<ComponentType>
}

const pluginModules = import.meta.glob<{ default: PluginPageDef[] }>(
  './**/plugins.ts',
)

const pluginCache = new Map<string, PluginPageDef[]>()

export async function getPluginPages(missionId: string): Promise<PluginPageDef[]> {
  const key = missionId.toLowerCase()
  const cached = pluginCache.get(key)
  if (cached) return cached

  const path = `./${key}/plugins.ts`
  const loader = pluginModules[path]
  if (!loader) return []

  const mod = await loader()
  const plugins = mod.default ?? []
  pluginCache.set(key, plugins)
  return plugins
}
