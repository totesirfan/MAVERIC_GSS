import type { MissionFacts, RxPacket } from '@/lib/types'

export interface MavericMissionFacts extends MissionFacts {
  id: 'maveric'
  facts: {
    header?: {
      cmd_id?: string | number
      src?: string | number
      dest?: string | number
      echo?: string | number
      ptype?: string | number
      [key: string]: unknown
    }
    protocol?: Record<string, unknown>
    integrity?: Record<string, unknown>
  }
}

export function mavericFacts(packet: RxPacket): MavericMissionFacts | null {
  return packet.mission?.id === 'maveric' ? packet.mission as MavericMissionFacts : null
}

export function mavericHeader(packet: RxPacket): MavericMissionFacts['facts']['header'] {
  return mavericFacts(packet)?.facts?.header ?? {}
}

export function mavericCmdId(packet: RxPacket): string {
  return String(mavericHeader(packet)?.cmd_id ?? '')
}

export function mavericPtype(packet: RxPacket): string {
  return String(mavericHeader(packet)?.ptype ?? '')
}

export function mavericSrc(packet: RxPacket): string {
  return String(mavericHeader(packet)?.src ?? '')
}

const IMAGING_CMD_REGEX = /^(img|cam|lcd)_/
const ERROR_PTYPES = new Set(['ERR', 'NACK', 'FAIL', 'TIMEOUT'])

export function isImagingRxPacket(p: RxPacket, imagingNodeSet: Set<string>): boolean {
  const cmdRaw = mavericCmdId(p)
  const ptype = mavericPtype(p).toUpperCase()
  const node = mavericSrc(p)
  return IMAGING_CMD_REGEX.test(cmdRaw) || (ERROR_PTYPES.has(ptype) && imagingNodeSet.has(node))
}
