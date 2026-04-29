/**
 * useEpsLive — derived EPS state from the platform ParametersProvider.
 *
 * The platform ParametersProvider (mounted at the App root) owns the
 * cross-navigation cache of live `{ v, t }` parameter entries; this
 * hook reads the EPS slice and accumulates the per-field "prev"
 * rotation, I_BAT charge-direction hysteresis, one-shot fault
 * latches, and per-link ingest counter on top of it.
 *
 * Trade-off: derived state (prev_fields, chargeDir, latched,
 * receivedThisLink) is owned by EpsPage and resets when the page
 * unmounts. The underlying parameter values are still root-cached
 * and replay correctly — only the trend indicators / latched
 * warnings start blank on a fresh EpsPage open.
 *
 * Single-consumer rule: EpsPage destructures and passes narrow props
 * to memo'd children; do not call this hook from leaf cards or every
 * field change will rerender the whole subtree.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { clearParameterGroup, useParameterGroup } from '@/state/parametersHooks'
import { useRxStatus } from '@/state/rxHooks'
import { chargeDirection } from './derive'
import type { EpsFieldName, EpsFieldMap, ChargeDir } from './types'
import { FIELD_DEFS } from './types'

interface EpsState {
  /** Latest value per field. Any subset of EpsFieldName may be present. */
  fields: EpsFieldMap
  /** Latest ingest timestamp per field (platform `t`). */
  field_t: EpsFieldMap
  /** The value each field had before the current one — per-field, not
   *  per-packet. Missing entries mean "never rotated yet". */
  prev_fields: EpsFieldMap
  /** Matching t for prev_fields. */
  prev_field_t: EpsFieldMap
  /** Any-field ingest events observed since the last session reset. */
  receivedThisLink: number
  linkGeneration: number
  chargeDir: ChargeDir
  /** Field name → received_at_ms of the first fire. Populated on
   *  VBRN1/VBRN2 > 0.1 V and on T_DIE ≥ 85 °C (junction limit).
   *  Cleared per-field by acknowledgeLatch() or wholesale by a
   *  cleared parameter group. */
  latched: Record<string, number>
  /** Raw eps_mode byte from beacon (FSW enum pending). */
  epsMode: number | null
  /** Timestamp of the latest eps_mode update. */
  epsModeT: number | null
  /** Raw eps_heartbeat byte — health flag: 1=alive, 0=dead. */
  epsHeartbeat: number | null
  /** Timestamp of the latest eps_heartbeat update. */
  epsHeartbeatT: number | null
}

export interface EpsLive extends EpsState {
  clearSnapshot: () => Promise<void>
  acknowledgeLatch: (field: string) => void
}

const EMPTY_MAP: EpsFieldMap = {}

const INITIAL_STATE: EpsState = {
  fields: EMPTY_MAP,
  field_t: EMPTY_MAP,
  prev_fields: EMPTY_MAP,
  prev_field_t: EMPTY_MAP,
  receivedThisLink: 0,
  linkGeneration: 0,
  chargeDir: 'idle',
  latched: {},
  epsMode: null,
  epsModeT: null,
  epsHeartbeat: null,
  epsHeartbeatT: null,
}

const LATCH_BURN_FIELDS = ['VBRN1', 'VBRN2'] as const
const LATCH_BURN_THRESHOLD_V = 0.1
const LATCH_T_DIE_JUNCTION_C = 85

const FIELD_NAMES: readonly EpsFieldName[] = FIELD_DEFS.map((d) => d.name)

export function useEpsLive(): EpsLive {
  const { byKey } = useParameterGroup('eps')
  const { sessionGeneration } = useRxStatus()
  const [state, setState] = useState<EpsState>(INITIAL_STATE)

  // I_BAT ring buffer for chargeDir hysteresis — kept in a ref so the
  // effect reads fresh values without resubscribing.
  const recentIBatsRef = useRef<number[]>([])
  const prevNonEmptyRef = useRef<boolean>(false)

  // React to parameter-group identity changes (one per ingest batch).
  useEffect(() => {
    let cancelled = false
    const isEmpty = Object.keys(byKey).length === 0
    const wasNonEmpty = prevNonEmptyRef.current
    prevNonEmptyRef.current = !isEmpty

    // Transition non-empty → empty: parameter group was cleared.
    if (isEmpty) {
      if (wasNonEmpty) {
        queueMicrotask(() => {
          if (cancelled) return
          recentIBatsRef.current = []
          setState((s) => ({
            ...s,
            fields: EMPTY_MAP,
            field_t: EMPTY_MAP,
            prev_fields: EMPTY_MAP,
            prev_field_t: EMPTY_MAP,
            latched: {},
            chargeDir: 'idle',
            epsMode: null,
            epsModeT: null,
            epsHeartbeat: null,
            epsHeartbeatT: null,
          }))
        })
      }
      return () => { cancelled = true }
    }

    // Per-field rotation. For each eps field in the group:
    //   if its `t` is newer than what we last recorded, rotate
    //   current -> prev for that single field. Fields that didn't
    //   change in this batch stay exactly where they were (including
    //   their prev slot), so a partial-source packet (e.g. a beacon
    //   touching only 7 fields) doesn't clobber prev_VOUT1 / etc.
    const isReplay = !wasNonEmpty

    queueMicrotask(() => {
      if (cancelled) return
      setState((s) => {
      const fields      = { ...s.fields }
      const field_t     = { ...s.field_t }
      const prev_fields = { ...s.prev_fields }
      const prev_field_t = { ...s.prev_field_t }
      let anyChanged = false

      for (const name of FIELD_NAMES) {
        const entry = byKey[name]
        if (!entry) continue
        const newT = entry.t
        const prevT = field_t[name]
        if (prevT !== undefined && newT <= prevT) continue

        const newV = typeof entry.v === 'number' ? entry.v : Number(entry.v)
        // Rotate prev first (value being displaced), then install new.
        if (prevT !== undefined && fields[name] !== undefined) {
          prev_fields[name]  = fields[name]
          prev_field_t[name] = prevT
        }
        fields[name]  = newV
        field_t[name] = newT
        anyChanged = true
      }

      // Beacon-only fields (not in FIELD_NAMES): track raw value + timestamp.
      let epsMode = s.epsMode
      let epsModeT = s.epsModeT
      const modeEntry = byKey['eps_mode']
      if (modeEntry && modeEntry.t !== epsModeT) {
        epsMode = typeof modeEntry.v === 'number' ? modeEntry.v : Number(modeEntry.v)
        epsModeT = modeEntry.t
        anyChanged = true
      }
      let epsHeartbeat = s.epsHeartbeat
      let epsHeartbeatT = s.epsHeartbeatT
      const hbEntry = byKey['eps_heartbeat']
      if (hbEntry && hbEntry.t !== epsHeartbeatT) {
        epsHeartbeat = typeof hbEntry.v === 'number' ? hbEntry.v : Number(hbEntry.v)
        epsHeartbeatT = hbEntry.t
        anyChanged = true
      }

      if (!anyChanged) return s

      // chargeDir — update from the latest I_BAT if it was one of the
      // fields that rotated this batch. (If I_BAT wasn't touched, the
      // ring buffer stays put.)
      let chargeDir = s.chargeDir
      const iBatT = field_t['I_BAT']
      const iBatTPrev = s.field_t['I_BAT']
      if (iBatT !== undefined && iBatT !== iBatTPrev) {
        const iBat = fields['I_BAT']
        if (typeof iBat === 'number' && Number.isFinite(iBat)) {
          recentIBatsRef.current = [...recentIBatsRef.current, iBat].slice(-3)
        }
        chargeDir = chargeDirection(
          typeof iBat === 'number' ? iBat : NaN,
          recentIBatsRef.current.slice(0, -1),
        )
      }

      // Latches — one-shot per field, fire on threshold crossings.
      const newLatched: Record<string, number> = { ...s.latched }
      for (const f of LATCH_BURN_FIELDS) {
        const v = fields[f as EpsFieldName]
        const t = field_t[f as EpsFieldName]
        if (typeof v === 'number' && t !== undefined
            && v > LATCH_BURN_THRESHOLD_V && !(f in newLatched)) {
          newLatched[f] = t
        }
      }
      const td = fields['T_DIE']
      const tdT = field_t['T_DIE']
      if (typeof td === 'number' && tdT !== undefined
          && td >= LATCH_T_DIE_JUNCTION_C && !('T_DIE_junction' in newLatched)) {
        newLatched['T_DIE_junction'] = tdT
      }

      return {
        ...s,
        fields,
        field_t,
        prev_fields,
        prev_field_t,
        receivedThisLink: isReplay ? s.receivedThisLink : s.receivedThisLink + 1,
        chargeDir,
        latched: newLatched,
        epsMode,
        epsModeT,
        epsHeartbeat,
        epsHeartbeatT,
      }
    })
    })
    return () => { cancelled = true }
  }, [byKey])

  // Session reset: keep current values (last-known satellite state is
  // deliberately persistent across operator session breaks), clear the
  // per-field prev map and the ring buffer, reset counter, bump link
  // generation. Latch set is NOT cleared — a deployment fault that
  // fired during the previous session is still unacknowledged.
  const lastSessionGenRef = useRef(sessionGeneration)
  useEffect(() => {
    if (sessionGeneration === lastSessionGenRef.current) return
    lastSessionGenRef.current = sessionGeneration
    let cancelled = false
    queueMicrotask(() => {
      if (cancelled) return
      setState((s) => ({
        ...s,
        prev_fields: EMPTY_MAP,
        prev_field_t: EMPTY_MAP,
        receivedThisLink: 0,
        linkGeneration: s.linkGeneration + 1,
        chargeDir: 'idle',
      }))
      recentIBatsRef.current = []
    })
    return () => { cancelled = true }
  }, [sessionGeneration])

  const clearSnapshot = useCallback(async () => {
    // Server broadcasts `{type:"parameters_cleared", group:"eps"}`
    // which the ParametersProvider turns into an empty group state;
    // our effect above picks the empty transition up and resets local
    // derived state.
    await clearParameterGroup('eps').catch(() => {})
  }, [])

  const acknowledgeLatch = useCallback((field: string) => {
    setState((s) => {
      if (!(field in s.latched)) return s
      const next = { ...s.latched }
      delete next[field]
      return { ...s, latched: next }
    })
  }, [])

  return { ...state, clearSnapshot, acknowledgeLatch }
}
