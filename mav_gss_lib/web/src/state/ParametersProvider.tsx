// mav_gss_lib/web/src/state/ParametersProvider.tsx
/**
 * ParametersProvider — flat parameter cache, single live-state source.
 *
 * State is pre-grouped by namespace so per-group hooks return ref-stable
 * slices: an EPS update yields a new top-level state object but
 * `state.grouped['gnc']` keeps its reference, enabling React.memo on
 * GNC cards to skip re-render. The component calling
 * useParameterGroup still re-runs (context changed) — only memoized
 * children benefit.
 *
 * Hooks:
 *   useParameter(name)              — single-parameter lookup with spec
 *   useParameterGroup(group)        — namespace slice, byKey-keyed
 *   clearParameterGroup(group)      — DELETE /api/parameters/group/{group}
 *
 * Author: Irfan Annuar - USC ISI SERC
 */
import {
  createContext, useContext, useEffect, useMemo, useState,
  type PropsWithChildren,
} from 'react'
import { authFetch } from '@/lib/auth'
import { usePluginRxCustomSubscription } from '@/hooks/usePluginServices'

export interface ParameterSpec {
  name: string                  // "<group>.<key>"
  group: string | null
  key: string
  type: string
  unit: string
  description: string
  enum: Record<string, number> | null
  tags: Record<string, unknown>
}

export interface ParameterEntry {
  v: unknown
  t: number
  display_only?: boolean
}

type GroupedState = Record<string, Record<string, ParameterEntry>>

interface LiveState {
  grouped: GroupedState
  timestamps: Record<string, number>
}

interface ParametersContextValue {
  grouped: GroupedState
  specByName: Map<string, ParameterSpec>
  specsByGroup: Record<string, ParameterSpec[]>
  timestamps: Record<string, number>
}

const EMPTY_LIVE: LiveState = { grouped: {}, timestamps: {} }
const EMPTY_BUCKET: Record<string, ParameterEntry> = {}
const EMPTY_LIST: ParameterSpec[] = []

const ParametersContext = createContext<ParametersContextValue | null>(null)

interface ParameterUpdateMsg {
  type: 'parameters'
  updates: Array<{ name: string; v: unknown; t: number; display_only?: boolean }>
  replay?: boolean
}

interface ParametersClearedMsg {
  type: 'parameters_cleared'
  group: string
}

function splitName(name: string): [string, string] {
  const dot = name.indexOf('.')
  return dot > 0 ? [name.slice(0, dot), name.slice(dot + 1)] : ['', name]
}

export function ParametersProvider({ children }: PropsWithChildren) {
  const subscribe = usePluginRxCustomSubscription()
  // grouped + timestamps share one state slot — a single setState updater
  // computes both atomically. Two separate setStates (or worse,
  // setTimestamps inside setGrouped) would violate React's
  // "updaters must be pure" rule and break under StrictMode / concurrent
  // rendering.
  const [live, setLive] = useState<LiveState>(EMPTY_LIVE)
  const [specByName, setSpecByName] = useState<Map<string, ParameterSpec>>(new Map())
  const [specsByGroup, setSpecsByGroup] = useState<Record<string, ParameterSpec[]>>({})

  // Spec fetch (once)
  useEffect(() => {
    fetch('/api/parameters')
      .then((r) => r.json())
      .then((body: { parameters: ParameterSpec[] }) => {
        const byName = new Map<string, ParameterSpec>()
        const byGroup: Record<string, ParameterSpec[]> = {}
        for (const p of body.parameters) {
          byName.set(p.name, p)
          const g = p.group ?? ''
          ;(byGroup[g] ??= []).push(p)
        }
        setSpecByName(byName)
        setSpecsByGroup(byGroup)
      })
      .catch(() => {})
  }, [])

  // WS subscription
  useEffect(() => {
    return subscribe((raw) => {
      const msg = raw as unknown as ParameterUpdateMsg | ParametersClearedMsg | { type?: string }

      if (msg.type === 'parameters_cleared') {
        const cleared = msg as ParametersClearedMsg
        setLive((prev) => {
          if (!prev.grouped[cleared.group] && !(cleared.group in prev.timestamps)) {
            return prev
          }
          const grouped = { ...prev.grouped }
          delete grouped[cleared.group]
          const timestamps = { ...prev.timestamps }
          delete timestamps[cleared.group]
          return { grouped, timestamps }
        })
        return
      }

      if (msg.type !== 'parameters') return
      const update = msg as ParameterUpdateMsg

      setLive((prev) => {
        // On replay, replace state wholesale. Otherwise only the groups
        // that received updates get a new inner-record reference;
        // unaffected groups keep their existing reference (so
        // React.memo'd children of those groups don't re-render).
        const baseGrouped: GroupedState = update.replay ? {} : prev.grouped
        const baseTimestamps: Record<string, number> = update.replay ? {} : prev.timestamps
        const grouped: GroupedState = { ...baseGrouped }
        const timestamps: Record<string, number> = { ...baseTimestamps }
        const dirty = new Set<string>()

        for (const u of update.updates) {
          const [group, key] = splitName(u.name)
          const cur = grouped[group] ?? {}
          if (cur[key] && u.t < cur[key].t) continue
          if (!dirty.has(group)) {
            grouped[group] = { ...cur }
            dirty.add(group)
          }
          grouped[group][key] = u.display_only
            ? { v: u.v, t: u.t, display_only: true }
            : { v: u.v, t: u.t }
          if (!timestamps[group] || u.t > timestamps[group]) {
            timestamps[group] = u.t
          }
        }

        if (dirty.size === 0 && !update.replay) return prev
        return { grouped, timestamps }
      })
    })
  }, [subscribe])

  const value = useMemo<ParametersContextValue>(
    () => ({
      grouped: live.grouped,
      specByName,
      specsByGroup,
      timestamps: live.timestamps,
    }),
    [live, specByName, specsByGroup],
  )
  return <ParametersContext.Provider value={value}>{children}</ParametersContext.Provider>
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
