/**
 * Magnetometer NVG file: no in-browser preview. Just a download button
 * and basic metadata. .nvg is binary sensor data; operator processes
 * it offline.
 */

import { colors } from '@/lib/colors';
import { filesEndpoint } from './helpers';
import type { FileLeaf } from './types';

interface Props { file: FileLeaf | null }

export function MagPreview({ file }: Props) {
  if (!file) {
    return (
      <div className="p-4 italic text-[11px]" style={{ color: colors.textMuted }}>
        select a file to download
      </div>
    );
  }
  const url = filesEndpoint('preview', file.kind, file.filename, file.source);
  return (
    <div className="flex flex-col h-full p-4 gap-2">
      <div className="text-[11px]" style={{ color: colors.textPrimary }}>{file.filename}</div>
      <div className="text-[10px]" style={{ color: colors.textMuted }}>
        {file.source ?? '—'} · {file.complete ? 'complete' : `${file.received}/${file.total ?? '—'}`}
        {file.chunk_size != null && ` · chunk ${file.chunk_size} B`}
      </div>
      <a
        href={url}
        download={file.filename}
        className="text-[11px] mt-2 px-3 py-1 border inline-block w-fit"
        style={{ borderColor: colors.active, color: colors.active }}
      >
        DOWNLOAD .nvg
      </a>
      <div className="text-[10px] mt-4" style={{ color: colors.textMuted }}>
        Binary sensor file — process offline.
      </div>
    </div>
  );
}
