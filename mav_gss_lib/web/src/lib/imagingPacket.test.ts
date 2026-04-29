import { describe, expect, it } from 'vitest'
import { isImagingRxPacket } from '@/plugins/maveric/missionFacts'
import type { RxPacket } from '@/lib/types'

function packet(cmd_id: string, ptype: string, src: string): RxPacket {
  return {
    num: 1,
    frame: 'ASM+GOLAY',
    size: 0,
    raw_hex: '',
    warnings: [],
    is_echo: false,
    is_dup: false,
    is_unknown: false,
    mission: {
      id: 'maveric',
      facts: {
        header: { cmd_id, ptype, src },
      },
    },
  }
}

describe('isImagingRxPacket', () => {
  it('matches imaging commands from canonical mission facts', () => {
    expect(isImagingRxPacket(packet('img_get_chunks', 'RES', 'HLNV'), new Set(['HLNV']))).toBe(true)
  })

  it('matches error packets from imaging nodes', () => {
    expect(isImagingRxPacket(packet('com_ping', 'NACK', 'HLNV'), new Set(['HLNV']))).toBe(true)
  })

  it('rejects non-imaging errors from other nodes', () => {
    expect(isImagingRxPacket(packet('com_ping', 'NACK', 'EPS'), new Set(['HLNV']))).toBe(false)
  })
})
