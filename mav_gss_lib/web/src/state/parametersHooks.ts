import { useContext } from 'react'
import { authFetch } from '@/lib/auth'
import {
  ParametersContext,
  type ParameterEntry,
  type ParameterSpec,
} from './parametersContexts'

const EMPTY_BUCKET: Record<string, ParameterEntry> = {}
const EMPTY_LIST: ParameterSpec[] = []

function splitName(name: string): [string, string] {
  const dot = name.indexOf('.')
  return dot > 0 ? [name.slice(0, dot), name.slice(dot + 1)] : ['', name]
}

export function useParameter(name: string): { entry?: ParameterEntry; spec?: ParameterSpec } {
  const ctx = useContext(ParametersContext)
  if (!ctx) throw new Error('useParameter outside ParametersProvider')
  const [group, key] = splitName(name)
  return {
    entry: ctx.grouped[group]?.[key],
    spec: ctx.specByName.get(name),
  }
}

export function useParameterGroup(group: string): {
  byKey: Record<string, ParameterEntry>
  specs: ParameterSpec[]
  lastUpdateAt: number | null
} {
  const ctx = useContext(ParametersContext)
  if (!ctx) throw new Error('useParameterGroup outside ParametersProvider')
  return {
    byKey: ctx.grouped[group] ?? EMPTY_BUCKET,
    specs: ctx.specsByGroup[group] ?? EMPTY_LIST,
    lastUpdateAt: ctx.timestamps[group] ?? null,
  }
}

export async function clearParameterGroup(group: string): Promise<void> {
  await authFetch(`/api/parameters/group/${group}`, { method: 'DELETE' })
}
