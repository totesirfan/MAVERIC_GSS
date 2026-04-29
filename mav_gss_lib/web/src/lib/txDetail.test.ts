import { describe, expect, it } from 'vitest'
import { txDetailBlocks, txParameterBlocks } from '@/lib/txDetail'
import type { TxQueueCmd } from '@/lib/types'

function item(overrides: Partial<TxQueueCmd> = {}): TxQueueCmd {
  return {
    type: 'mission_cmd',
    num: 1,
    cmd_id: 'set_mode',
    mission: {
      id: 'test',
      facts: {
        header: { cmd_id: 'set_mode' },
        protocol: {
          args_hex: '02',
          args_len: 1,
        },
      },
    },
    parameters: [],
    guard: false,
    size: 1,
    raw_hex: '02',
    payload: {},
    ...overrides,
  }
}

describe('tx detail blocks', () => {
  it('does not invent Args blocks without typed parameters', () => {
    expect(txParameterBlocks(item())).toEqual([])
  })

  it('renders protocol metadata blocks', () => {
    const protocol = txDetailBlocks(item()).find((block) => block.kind === 'protocol')

    expect(protocol?.fields.map((field) => field.name)).toEqual(['Args Hex', 'Args Len'])
  })

  it('prefers typed parameters when they are present', () => {
    const blocks = txParameterBlocks(item({
      parameters: [{ name: 'cmd.mode', value: 3, ts_ms: 0 }],
    }))

    expect(blocks).toEqual([
      { kind: 'args', label: 'Cmd', fields: [{ name: 'Mode', value: '3' }] },
    ])
  })
})
