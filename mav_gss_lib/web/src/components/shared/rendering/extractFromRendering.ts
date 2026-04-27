import type { RenderingData } from '@/lib/types'

/** Extract copyable command text from _rendering. */
export function extractFromRendering(rendering: Pick<RenderingData, 'row' | 'detail_blocks'> | undefined): { cmd: string; args: string } {
  const cmdValue = rendering?.row?.cmd?.value
  if (cmdValue) {
    return { cmd: String(cmdValue), args: String(cmdValue) }
  }
  const blocks = rendering?.detail_blocks ?? []
  let cmd = ''
  const argParts: string[] = []
  for (const block of blocks) {
    if (block.kind !== 'command') continue
    for (const f of block.fields ?? []) {
      if (f.name === 'Command') cmd = f.value
      else argParts.push(`${f.name}=${f.value}`)
    }
  }
  return { cmd, args: argParts.join(', ') }
}
