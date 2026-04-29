import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MavericTxBuilder from './TxBuilder'

const schema = {
  com_ping: {
    tx_args: [],
    nodes: ['LPPM'],
  },
}

const identity = {
  mission_name: 'MAVERIC',
  nodes: {
    GS: '0',
    LPPM: '1',
  },
  ptypes: {},
  node_descriptions: {},
  gs_node: 'GS',
}

function mockBuilderFetch() {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/schema') {
      return Promise.resolve(new Response(JSON.stringify(schema)))
    }
    if (url === '/api/plugins/maveric/identity') {
      return Promise.resolve(new Response(JSON.stringify(identity)))
    }
    return Promise.reject(new Error(`Unexpected fetch: ${url}`))
  }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
  Element.prototype.scrollIntoView = vi.fn()
})

describe('MavericTxBuilder', () => {
  it('queues a no-arg command when Enter is pressed on the focused Queue button', async () => {
    mockBuilderFetch()
    const onQueue = vi.fn()

    render(<MavericTxBuilder onQueue={onQueue} onClose={() => {}} />)

    fireEvent.click(await screen.findByText('com_ping'))

    const queueButton = await screen.findByRole('button', { name: /queue/i })
    await waitFor(() => expect(document.activeElement).toBe(queueButton))

    fireEvent.keyDown(queueButton, { key: 'Enter' })

    expect(onQueue).toHaveBeenCalledTimes(1)
    expect(onQueue).toHaveBeenCalledWith({
      cmd_id: 'com_ping',
      args: {},
      packet: { dest: 'LPPM' },
      guard: false,
    })
  })
})
