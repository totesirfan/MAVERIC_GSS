/** TelemetryProvider tests.
 *
 * Mocks usePluginRxCustomSubscription and exercises the provider's
 * domain-slice merge, LWW ordering, replay snapshot, and shared
 * catalog fetch (with 404 memoization).
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { act, render } from '@testing-library/react'
import { createElement, type ReactElement } from 'react'

type RxMessage = Record<string, unknown>
type RxSubscriber = (msg: RxMessage) => void

let mockSubscribers: RxSubscriber[] = []

vi.mock('@/hooks/usePluginServices', () => ({
  usePluginRxCustomSubscription: () => (fn: RxSubscriber) => {
    mockSubscribers.push(fn)
    return () => { mockSubscribers = mockSubscribers.filter((s) => s !== fn) }
  },
}))

import { TelemetryProvider, useTelemetry, useTelemetryCatalog } from './TelemetryProvider'

function Wrap(children: ReactElement) {
  return createElement(TelemetryProvider, null, children)
}

function dispatch(msg: RxMessage) {
  act(() => {
    for (const s of mockSubscribers) s(msg)
  })
}

// Consumer component that renders the live state of one domain.
function DomainProbe({ domain, onState }: { domain: string; onState: (s: unknown) => void }) {
  const state = useTelemetry(domain)
  onState(state)
  return null
}

function CatalogProbe<T>({ domain, onCatalog }: { domain: string; onCatalog: (c: T | null) => void }) {
  const catalog = useTelemetryCatalog<T>(domain)
  onCatalog(catalog)
  return null
}


describe('TelemetryProvider — state slice', () => {
  beforeEach(() => {
    mockSubscribers = []
  })

  it('ignores messages that are not type=telemetry', () => {
    const snapshots: unknown[] = []
    render(Wrap(createElement(DomainProbe, { domain: 'eps', onState: (s) => snapshots.push(s) })))
    dispatch({ type: 'not_telemetry', domain: 'eps', changes: { V_BAT: { v: 7.6, t: 100 } } })
    // Final snapshot is still the empty {} that useTelemetry returns.
    expect(snapshots[snapshots.length - 1]).toEqual({})
  })

  it('applies changes into the correct domain slice', () => {
    const snapshots: unknown[] = []
    render(Wrap(createElement(DomainProbe, { domain: 'eps', onState: (s) => snapshots.push(s) })))
    dispatch({
      type: 'telemetry', domain: 'eps',
      changes: { V_BAT: { v: 7.6, t: 100 } },
    })
    expect(snapshots[snapshots.length - 1]).toEqual({ V_BAT: { v: 7.6, t: 100 } })
  })

  it('per-key LWW drops older entries', () => {
    const snapshots: unknown[] = []
    render(Wrap(createElement(DomainProbe, { domain: 'eps', onState: (s) => snapshots.push(s) })))
    dispatch({ type: 'telemetry', domain: 'eps', changes: { V_BAT: { v: 7.6, t: 200 } } })
    dispatch({ type: 'telemetry', domain: 'eps', changes: { V_BAT: { v: 7.5, t: 100 } } })
    const last = snapshots[snapshots.length - 1] as Record<string, { v: number; t: number }>
    expect(last.V_BAT).toEqual({ v: 7.6, t: 200 })
  })

  it('replay wipes prior state in that domain', () => {
    const snapshots: unknown[] = []
    render(Wrap(createElement(DomainProbe, { domain: 'eps', onState: (s) => snapshots.push(s) })))
    dispatch({ type: 'telemetry', domain: 'eps', changes: { V_BAT: { v: 7.6, t: 100 } } })
    dispatch({
      type: 'telemetry', domain: 'eps', replay: true,
      changes: { I_BAT: { v: 0.5, t: 200 } },
    })
    const last = snapshots[snapshots.length - 1] as Record<string, { v: number; t: number }>
    expect(Object.keys(last)).toEqual(['I_BAT'])
  })

  it('cleared resets the domain slice to empty', () => {
    const snapshots: unknown[] = []
    render(Wrap(createElement(DomainProbe, { domain: 'eps', onState: (s) => snapshots.push(s) })))
    dispatch({ type: 'telemetry', domain: 'eps', changes: { V_BAT: { v: 7.6, t: 100 } } })
    dispatch({ type: 'telemetry', domain: 'eps', cleared: true })
    expect(snapshots[snapshots.length - 1]).toEqual({})
  })

  it('domains are isolated from each other', () => {
    const eps: unknown[] = []
    const gnc: unknown[] = []
    render(
      Wrap(
        createElement('div', null,
          createElement(DomainProbe, { domain: 'eps', onState: (s) => eps.push(s) }),
          createElement(DomainProbe, { domain: 'gnc', onState: (s) => gnc.push(s) }),
        ),
      ),
    )
    dispatch({ type: 'telemetry', domain: 'eps', changes: { V_BAT: { v: 7.6, t: 100 } } })
    expect(eps[eps.length - 1]).toEqual({ V_BAT: { v: 7.6, t: 100 } })
    expect(gnc[gnc.length - 1]).toEqual({})
  })
})


describe('TelemetryProvider — catalog', () => {
  beforeEach(() => {
    mockSubscribers = []
    vi.restoreAllMocks()
  })

  it('fetches catalog once and caches across consumers', async () => {
    const body = [{ name: 'STAT', unit: '' }]
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => body,
    } as Response)
    vi.stubGlobal('fetch', fetchMock)

    const cats1: unknown[] = []
    const cats2: unknown[] = []
    render(
      Wrap(
        createElement('div', null,
          createElement(CatalogProbe, { domain: 'gnc', onCatalog: (c) => cats1.push(c) }),
          createElement(CatalogProbe, { domain: 'gnc', onCatalog: (c) => cats2.push(c) }),
        ),
      ),
    )
    await act(async () => { await Promise.resolve() })
    await act(async () => { await Promise.resolve() })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith('/api/telemetry/gnc/catalog')
    expect(cats1[cats1.length - 1]).toEqual(body)
    expect(cats2[cats2.length - 1]).toEqual(body)
  })

  it('remembers 404 and does not re-fetch', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 404 } as Response)
    vi.stubGlobal('fetch', fetchMock)

    const cats: unknown[] = []
    const { rerender } = render(
      Wrap(createElement(CatalogProbe, { domain: 'eps', onCatalog: (c) => cats.push(c) })),
    )
    await act(async () => { await Promise.resolve() })
    // Re-render the same consumer — provider should not re-fetch after 404.
    rerender(
      Wrap(createElement(CatalogProbe, { domain: 'eps', onCatalog: (c) => cats.push(c) })),
    )
    await act(async () => { await Promise.resolve() })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(cats[cats.length - 1]).toBeNull()
  })
})
