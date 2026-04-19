import { defaultFilter } from 'cmdk'

// cmdk's default filter is a permissive subsequence matcher — typing "gnc"
// scores "Toggle Uplink Echoes" at ~0.005 (g-toggle, n-uplink, c-echoes).
// That pollutes results when the user is after a specific term. A small
// threshold drops those stray matches while still admitting legitimate
// non-prefix matches (e.g. "upl" → "Toggle Uplink Echoes" at ~0.89).
const THRESHOLD = 0.01

export function strictFilter(value: string, search: string, keywords?: string[]): number {
  const s = defaultFilter(value, search, keywords)
  return s >= THRESHOLD ? s : 0
}
