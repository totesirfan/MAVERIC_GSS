/**
 * URL builders and small utilities shared by Imaging and Files pages.
 */

import type { FileKind } from './types';

export function filesEndpoint(
  action: 'status' | 'files' | 'chunks' | 'preview' | 'file',
  kind: FileKind,
  filename?: string,
  source?: string | null,
): string {
  const params = new URLSearchParams({ kind });
  if (source) params.set('source', source);
  const qs = params.toString();
  if (action === 'status' || action === 'files') {
    return `/api/plugins/files/${action}?${qs}`;
  }
  if (!filename) throw new Error(`filesEndpoint(${action}) requires a filename`);
  const encoded = encodeURIComponent(filename).replace(/%2F/g, '/');
  return `/api/plugins/files/${action}/${encoded}?${qs}`;
}
