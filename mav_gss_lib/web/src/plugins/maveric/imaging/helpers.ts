// MAVERIC imaging-panel shared helpers, constants, and types.

/**
 * Default value for the `Destination` wire argument in img_cnt_chunks and
 * img_get_chunk commands. This is a satellite-side integer, distinct from
 * the routing node id. Current OBC firmware uses "2" in testing; override
 * from the form's "target" field if the payload accepts a different value.
 */
export const DEFAULT_DEST_ARG = '2'

/** Default bytes per chunk for img_cnt_chunks if the operator leaves it blank. */
export const DEFAULT_CHUNK_SIZE = '150'

/** Append `.jpg` if the filename doesn't already end in `.jpg` or `.jpeg`. */
export const withJpg = (s: string): string =>
  /\.jpe?g$/i.test(s) ? s : `${s}.jpg`

export interface ImagingFileStatus {
  filename: string
  received: number
  total: number | null
  complete: boolean
}

/** Fetch `/api/plugins/imaging/status` and return its `files` array. */
export async function fetchImagingStatus(): Promise<ImagingFileStatus[]> {
  try {
    const r = await fetch('/api/plugins/imaging/status')
    if (!r.ok) return []
    const data = await r.json()
    return (data.files ?? []) as ImagingFileStatus[]
  } catch {
    return []
  }
}

/** Collapse missing chunk indices into ranges: [5,6,7,10,15] → ["5–7","10","15"] */
export function formatMissingRanges(missing: number[]): string[] {
  if (missing.length === 0) return []
  const ranges: string[] = []
  let start = missing[0]
  let end = start
  for (let i = 1; i < missing.length; i++) {
    if (missing[i] === end + 1) {
      end = missing[i]
    } else {
      ranges.push(start === end ? `${start}` : `${start}–${end}`)
      start = missing[i]
      end = start
    }
  }
  ranges.push(start === end ? `${start}` : `${start}–${end}`)
  return ranges
}
