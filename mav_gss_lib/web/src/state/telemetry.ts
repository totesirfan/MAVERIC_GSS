// Platform telemetry types — shared by TelemetryProvider and any
// mission-local consumer that imports live domain state or catalog.
//
// Platform contract: an entry MUST carry `t` (ms since epoch) — that's
// the one field the provider compares when merging. Everything else is
// mission-extensible. The default backend policy `lww_by_ts` writes
// `{ v, t }`, and every MAVERIC mission extractor today emits that
// shape, so `v: unknown` is kept as a convenience field on the type.
// A mission that ships a custom merge policy returning, say,
// `{ v, t, seq, src }` or `{ components, t }` is equally valid — the
// provider doesn't care. Use index-signature access (`entry['seq']`)
// for any non-{v,t} field so the platform type doesn't lie about the
// mission shape it never sees.
export type TelemetryEntry = { t: number; v?: unknown; [extra: string]: unknown }
export type TelemetryDomainState = Record<string, TelemetryEntry>

export interface TelemetryMsg {
  type: 'telemetry'
  domain: string
  changes?: TelemetryDomainState
  replay?: boolean
  cleared?: boolean
}
