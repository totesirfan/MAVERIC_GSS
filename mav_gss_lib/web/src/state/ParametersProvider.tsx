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
 * Consumer hooks (useParameter, useParameterGroup, clearParameterGroup)
 * live in `./parametersHooks`. Type + context surface lives in
 * `./parametersContexts`.
 *
 * Author: Irfan Annuar - USC ISI SERC
 */
import { useEffect, useMemo, useState, type PropsWithChildren } from 'react'
import { usePluginRxCustomSubscription } from '@/hooks/usePluginServices'
import {
  ParametersContext,
  type ParametersContextValue,
  type ParameterEntry,
  type ParameterSpec,
  type ContainerFreshness,
} from './parametersContexts'

type GroupedState = Record<string, Record<string, ParameterEntry>>

interface LiveState {
  grouped: GroupedState
  timestamps: Record<string, number>
}

interface FreshnessMsg {
  type: 'parameters_freshness'
  container: string
  last_ms: number
  expected_period_ms: number
}

interface ParameterUpdateMsg {
  type: 'parameters'
  updates: Array<{ name: string; v: unknown; t: number; display_only?: boolean }>
  replay?: boolean
}

interface ParametersClearedMsg {
  type: 'parameters_cleared'
  group: string
}

const EMPTY_LIVE: LiveState = { grouped: {}, timestamps: {} }

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
  const [freshness, setFreshness] = useState<Record<string, ContainerFreshness>>({})

  // Spec fetch (once)
  useEffect(() => {
    fetch('/api/parameters')
      .then((r) => r.json())
      .then((body: { parameters: ParameterSpec[]; freshness?: Record<string, ContainerFreshness> }) => {
        const byName = new Map<string, ParameterSpec>()
        const byGroup: Record<string, ParameterSpec[]> = {}
        for (const p of body.parameters) {
          byName.set(p.name, p)
          const g = p.group ?? ''
          ;(byGroup[g] ??= []).push(p)
        }
        setSpecByName(byName)
        setSpecsByGroup(byGroup)
        if (body.freshness) setFreshness(body.freshness)
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

      if (msg.type === 'parameters_freshness') {
        const f = msg as FreshnessMsg
        setFreshness(prev => ({
          ...prev,
          [f.container]: { last_ms: f.last_ms, expected_period_ms: f.expected_period_ms || null },
        }))
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
      freshness,
    }),
    [live, specByName, specsByGroup, freshness],
  )
  return <ParametersContext.Provider value={value}>{children}</ParametersContext.Provider>
}
