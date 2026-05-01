import { useState, useEffect, useMemo, useCallback } from 'react';
import { ConfirmDialog } from '@/components/shared/dialogs/ConfirmDialog';
import { showToast } from '@/components/shared/overlays/StatusToast';
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable';
import { usePluginServices } from '@/hooks/usePluginServices';
import { useNowMs } from '@/hooks/useNowMs';
import { useColumnDefs } from '@/state/sessionHooks';
import { composeRxColumns } from '@/lib/columns';
import { isImagingRxPacket } from './missionFacts';
import type { RxPacket } from '@/lib/types';

import { RxLogPanel } from './imaging/RxLogPanel';
import { TxControlsPanel } from './imaging/TxControlsPanel';
import { ProgressPanel } from './imaging/ProgressPanel';
import { PreviewPanel } from './imaging/PreviewPanel';
import { QueuePanel } from './imaging/QueuePanel';
import { useImageFiles } from './files/FileChunkContext';
import type { FileLeaf, MissingRange } from './imaging/types';
import { imagingFileEndpoint } from './imaging/helpers';

const FALLBACK_IMAGING_NODES = new Set(['HLNV', 'ASTR']);

export default function ImagingPage() {
  const {
    packets: rxPackets,
    config,
    queueCommand,
    txConnected,
    fetchSchema,
    sendAll,
    abortSend,
    sendProgress,
    pendingQueue,
    removeQueueItem,
  } = usePluginServices();

  const {
    files,
    selectedId,
    previewTab,
    previewVersion,
    destNode,
    setSelectedId,
    setPreviewTab,
    setDestNode,
    refetch,
  } = useImageFiles();

  const nowMs = useNowMs();

  // ── TX routing + schema ─────────────────────────────────────────
  const [schema, setSchema] = useState<Record<string, Record<string, unknown>> | null>(null);

  // ── Delete confirm ──────────────────────────────────────────────
  const [deleteTarget, setDeleteTarget] = useState<FileLeaf[] | null>(null);

  // ── Column defs (shared with main dashboard via SessionProvider) ─
  // Pop-out windows render outside SessionProvider (hasProvider=false) and
  // fall back to local fetches. Main window reads from context.
  const { defs: ctxDefs } = useColumnDefs();
  const rxColumns = ctxDefs?.rx ?? composeRxColumns([]);
  const txColumns = ctxDefs?.tx ?? [];

  useEffect(() => {
    fetchSchema().then(setSchema).catch(() => {});
  }, [fetchSchema]);

  const imagingNodeSet = useMemo<Set<string>>(() => {
    const fromSchema = (schema?.img_get_chunks as { nodes?: string[] } | undefined)?.nodes;
    if (fromSchema && fromSchema.length > 0) return new Set(fromSchema);
    return FALLBACK_IMAGING_NODES;
  }, [schema]);
  const nodes = useMemo(() => {
    const imgCmd = schema?.img_get_chunks ?? schema?.img_cnt_chunks;
    const allowedNodes = ((imgCmd as { nodes?: string[] } | undefined)?.nodes) ?? [];
    return allowedNodes.length > 0 ? allowedNodes : Array.from(FALLBACK_IMAGING_NODES);
  }, [schema]);
  const selected = useMemo(
    () => files.find((f) => f.id === selectedId) ?? null,
    [files, selectedId],
  );
  const selectedSource = selected?.source && nodes.includes(selected.source) ? selected.source : '';
  const effectiveDestNode = destNode || selectedSource || nodes[0] || '';

  // Thumbnail-filename prefix, e.g. "tn_". Feeds the FilenameInput tag
  // and the destination-from-filename helper in TxControlsPanel.
  const thumbPrefix =
    (config?.mission.config.imaging as { thumb_prefix?: string } | undefined)?.thumb_prefix ?? '';

  // Imaging-filtered RX log — preserves full RxPacket so shared
  // PacketList can render them with the same columns as the main dashboard.
  const imagingPackets = useMemo<RxPacket[]>(() => {
    const rows: RxPacket[] = [];
    for (const p of rxPackets) {
      if (!isImagingRxPacket(p, imagingNodeSet)) continue;
      rows.push(p);
    }
    return rows;
  }, [rxPackets, imagingNodeSet]);

  const lastImagingPacketMs = imagingPackets[imagingPackets.length - 1]?.received_at_ms ?? null;
  const receiving = lastImagingPacketMs !== null && nowMs - lastImagingPacketMs < 1500;

  const handleSelectFile = useCallback(
    (id: string) => {
      const match = files.find((f) => f.id === id);
      if (match?.source && nodes.includes(match.source)) {
        setDestNode(match.source);
      }
      setSelectedId(id);
    },
    [files, nodes, setDestNode, setSelectedId],
  );

  // Stage re-request — auto-routes target per side
  const stageRerequest = useCallback(
    (side: 'thumb' | 'full', leaf: FileLeaf, ranges: MissingRange[]) => {
      const forcedTarget = side === 'thumb' ? '2' : '1';
      for (const r of ranges) {
        queueCommand({
          cmd_id: 'img_get_chunks',
          args: {
            filename: leaf.filename,
            start_chunk: String(r.start),
            num_chunks: String(r.count),
            destination: forcedTarget,
          },
          packet: { dest: leaf.source || effectiveDestNode },
        });
      }
      showToast(
        `Staged ${ranges.length} re-request${ranges.length === 1 ? '' : 's'} (${side})`,
        'success',
        'tx',
      );
    },
    [effectiveDestNode, queueCommand],
  );

  // Delete every real leaf in a pair (full side and thumb side). After
  // refetch, reset selection if the previously-selected id no longer
  // exists in the fresh list.
  const performDelete = useCallback(
    (leaves: FileLeaf[]) => {
      Promise.all(
        leaves.map((leaf) =>
          fetch(imagingFileEndpoint('file', leaf), { method: 'DELETE' })
            .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}: ${leaf.id}`)))),
        ),
      )
        .then(async () => {
          const fresh = await refetch();
          if (!fresh.find((f) => f.id === selectedId)) {
            setSelectedId(fresh[0]?.id ?? '');
          }
          showToast(`Deleted ${leaves.map((leaf) => leaf.id).join(' + ')}`, 'success', 'tx');
        })
        .catch((err) => showToast(`Failed to delete: ${err.message}`, 'error', 'tx'));
    },
    [refetch, selectedId, setSelectedId],
  );

  return (
    <div className="flex-1 flex overflow-hidden p-3">
      <ResizablePanelGroup className="flex-1 h-full">
        <ResizablePanel defaultSize={42} minSize={25}>
          <div className="flex flex-col gap-3 h-full min-w-0">
            <div className="h-[200px] shrink-0 flex flex-col">
              <RxLogPanel packets={imagingPackets} columns={rxColumns} receiving={receiving} />
            </div>
            <TxControlsPanel
              nodes={nodes}
              destNode={effectiveDestNode}
              onDestNodeChange={setDestNode}
              selected={selected}
              previewTab={previewTab}
              thumbPrefix={thumbPrefix}
              queueCommand={queueCommand}
              schema={schema}
              txConnected={txConnected}
            />
            <QueuePanel
              pendingQueue={pendingQueue}
              txColumns={txColumns}
              sendProgress={sendProgress}
              sendAll={sendAll}
              abortSend={abortSend}
              removeQueueItem={removeQueueItem}
            />
          </div>
        </ResizablePanel>
        <ResizableHandle
          withHandle
          className="mx-1 w-1 rounded-full bg-transparent hover:bg-[#222222] data-[resize-handle-active]:bg-[#30C8E0] transition-colors"
        />
        <ResizablePanel defaultSize={58} minSize={25}>
          <div className="flex flex-col gap-3 h-full min-w-0">
            <ProgressPanel
              files={files}
              selected={selected}
              onSelect={handleSelectFile}
              onDelete={setDeleteTarget}
              onStageRerequest={stageRerequest}
            />
            <PreviewPanel
              selected={selected}
              activeTab={previewTab}
              onTabChange={setPreviewTab}
              version={previewVersion}
            />
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete image?"
        detail={
          deleteTarget
            ? `${deleteTarget.map((leaf) => leaf.id).join(' + ')} and all chunks will be removed from disk. This cannot be undone.`
            : undefined
        }
        variant="destructive"
        onConfirm={() => {
          if (deleteTarget) performDelete(deleteTarget);
          setDeleteTarget(null);
        }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
