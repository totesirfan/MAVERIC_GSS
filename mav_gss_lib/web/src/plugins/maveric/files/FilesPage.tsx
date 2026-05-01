/**
 * Combined Files page for AII (JSON) + Mag (NVG) downlinks.
 *
 * Imaging stays on its own page (rich JPEG UX). This page is for
 * non-image artifacts that don't need format-specific viewers.
 */

import { useMemo, useState } from 'react';
import { ConfirmDialog } from '@/components/shared/dialogs/ConfirmDialog';
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable';
import { colors } from '@/lib/colors';
import { useFileChunks } from './FileChunkContext';
import { FilesTable } from './FilesTable';
import { JsonPreview } from './JsonPreview';
import { MagPreview } from './MagPreview';
import { filesEndpoint } from './helpers';
import type { FileLeaf } from './types';

type FilterKind = 'all' | 'aii' | 'mag';

const FILTER_OPTIONS: ReadonlyArray<{ id: FilterKind; label: string }> = [
  { id: 'all', label: 'ALL' },
  { id: 'aii', label: 'AII' },
  { id: 'mag', label: 'MAG' },
];

export default function FilesPage() {
  const { aiiFiles, magFiles, refetchAii, refetchMag } = useFileChunks();
  const [filter, setFilter] = useState<FilterKind>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<FileLeaf | null>(null);

  const allFiles = useMemo<FileLeaf[]>(() => {
    const merged = [...aiiFiles, ...magFiles];
    merged.sort((a, b) => (b.last_activity_ms ?? 0) - (a.last_activity_ms ?? 0));
    return merged;
  }, [aiiFiles, magFiles]);

  const filtered = useMemo(() => {
    if (filter === 'all') return allFiles;
    return allFiles.filter((f) => f.kind === filter);
  }, [allFiles, filter]);

  const selected = useMemo(
    () => filtered.find((f) => f.id === selectedId) ?? null,
    [filtered, selectedId],
  );

  const handleDelete = async (file: FileLeaf) => {
    const url = filesEndpoint('file', file.kind, file.filename, file.source);
    await fetch(url, { method: 'DELETE' });
    if (file.kind === 'aii') await refetchAii();
    else await refetchMag();
    setDeleteTarget(null);
    if (selectedId === file.id) setSelectedId(null);
  };

  return (
    <div className="flex flex-col h-full" style={{ background: colors.bgApp, color: colors.textPrimary }}>
      <div
        className="flex items-center gap-2 px-3 py-2 border-b"
        style={{ borderColor: colors.borderSubtle }}
      >
        <span className="text-[10px]" style={{ color: colors.textMuted }}>FILTER:</span>
        {FILTER_OPTIONS.map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setFilter(id)}
            className="text-[10px] px-2 py-[2px] border"
            style={{
              borderColor: filter === id ? colors.active : colors.borderStrong,
              color: filter === id ? colors.active : colors.textMuted,
            }}
          >
            {label}
          </button>
        ))}
        <span className="text-[10px] ml-auto" style={{ color: colors.textMuted }}>
          {filtered.length} file(s)
        </span>
      </div>

      <ResizablePanelGroup direction="horizontal" className="flex-1">
        <ResizablePanel defaultSize={60} minSize={30}>
          <div className="h-full overflow-auto">
            <FilesTable
              files={filtered}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onDelete={(f) => setDeleteTarget(f)}
            />
          </div>
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize={40} minSize={20}>
          {selected?.kind === 'aii'
            ? <JsonPreview file={selected} />
            : <MagPreview file={selected} />}
        </ResizablePanel>
      </ResizablePanelGroup>

      {deleteTarget && (
        <ConfirmDialog
          open
          title="Delete file?"
          detail={`Remove ${deleteTarget.filename}? This cannot be undone.`}
          variant="destructive"
          onConfirm={() => handleDelete(deleteTarget)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
