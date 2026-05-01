/**
 * JSON preview pane for AII files. Fetches the assembled file
 * via /api/plugins/files/preview?kind=aii and renders pretty-printed.
 */

import { useEffect, useState } from 'react';
import { colors } from '@/lib/colors';
import { filesEndpoint } from './helpers';
import type { FileLeaf } from './types';

interface Props { file: FileLeaf | null }

export function JsonPreview({ file }: Props) {
  const [text, setText] = useState<string>('');
  const [valid, setValid] = useState<boolean | null>(null);

  useEffect(() => {
    if (!file) { setText(''); setValid(null); return; }
    let cancelled = false;
    void (async () => {
      try {
        const r = await fetch(filesEndpoint('preview', file.kind, file.filename, file.source));
        if (!r.ok) { if (!cancelled) setText(`(no data — HTTP ${r.status})`); return; }
        const raw = await r.text();
        if (cancelled) return;
        try {
          const parsed = JSON.parse(raw);
          setText(JSON.stringify(parsed, null, 2));
          setValid(true);
        } catch {
          setText(raw);
          setValid(false);
        }
      } catch {
        if (!cancelled) setText('(fetch failed)');
      }
    })();
    return () => { cancelled = true; };
  }, [file]);

  if (!file) {
    return (
      <div className="p-4 italic text-[11px]" style={{ color: colors.textMuted }}>
        select a file to preview
      </div>
    );
  }
  return (
    <div className="flex flex-col h-full">
      <div className="text-[10px] px-2 py-1 border-b" style={{ color: colors.textMuted, borderColor: colors.borderSubtle }}>
        {file.filename} · {file.complete ? 'complete' : `${file.received}/${file.total ?? '—'}`}
        {valid === false && (
          <span className="ml-2" style={{ color: colors.danger }}>(invalid JSON)</span>
        )}
      </div>
      <pre
        className="flex-1 overflow-auto text-[11px] font-mono p-2"
        style={{ background: colors.bgApp, color: colors.textPrimary }}
      >{text}</pre>
    </div>
  );
}
