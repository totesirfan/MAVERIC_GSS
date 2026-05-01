// MAVERIC imaging-panel shared helpers, constants, and types.
//
// API-compatible with the pre-redesign helpers; routes through the new
// /api/plugins/files surface under the hood (kind=image).
//
// `PairedFile` is the legacy name for `ImagePair` and lives in
// `./types` (the imaging-page-local re-export). Everything else lives
// in `../files/types`.

import { filesEndpoint } from '../files/helpers';
import type { ImageStatusResponse } from '../files/types';
import type { FileLeaf, MissingRange, PairedFile } from './types';

export type { PairedFile, FileLeaf, MissingRange };

/** Append `.jpg` if the filename doesn't already end in `.jpg` or `.jpeg`. */
export const withJpg = (s: string): string =>
  /\.jpe?g$/i.test(s) ? s : `${s}.jpg`;

/** Fetch status (paired image view) and return the paired files array. */
export async function fetchImagingStatus(): Promise<PairedFile[]> {
  try {
    const r = await fetch(filesEndpoint('status', 'image'));
    if (!r.ok) return [];
    const data = (await r.json()) as ImageStatusResponse;
    return data.files ?? [];
  } catch {
    return [];
  }
}

/** Image-page endpoint helper — always pins kind='image'. Legacy
 *  signature: ``imagingFileEndpoint(action, leaf)`` taking a leaf
 *  with ``filename`` and ``source``. */
export function imagingFileEndpoint(
  action: 'chunks' | 'file' | 'preview',
  leaf: Pick<FileLeaf, 'filename' | 'source'>,
): string {
  return filesEndpoint(action, 'image', leaf.filename, leaf.source);
}

/** Collapse a sorted list of missing chunk indices into contiguous ranges.
 *  Unchanged from the legacy implementation — only imaging consumes it. */
export function computeMissingRanges(
  total: number | null,
  received: Set<number>,
): MissingRange[] {
  if (!total) return [];
  const missing: number[] = [];
  for (let i = 0; i < total; i++) {
    if (!received.has(i)) missing.push(i);
  }
  if (missing.length === 0) return [];
  const ranges: MissingRange[] = [];
  let start = missing[0];
  let end = start;
  for (let i = 1; i < missing.length; i++) {
    if (missing[i] === end + 1) {
      end = missing[i];
    } else {
      ranges.push({ start, end, count: end - start + 1 });
      start = missing[i];
      end = start;
    }
  }
  ranges.push({ start, end, count: end - start + 1 });
  return ranges;
}
