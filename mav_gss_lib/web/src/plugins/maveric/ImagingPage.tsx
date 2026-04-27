import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { ConfirmDialog } from '@/components/shared/dialogs/ConfirmDialog';
import { showToast } from '@/components/shared/overlays/StatusToast';
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable';
import { usePluginServices } from '@/hooks/usePluginServices';
import { useColumnDefs } from '@/state/sessionHooks';
import { renderingText } from '@/lib/rendering';
import type { ColumnDef, RxPacket, TxColumnDef } from '@/lib/types';

import { RxLogPanel } from './imaging/RxLogPanel';
import { TxControlsPanel } from './imaging/TxControlsPanel';
import { ProgressPanel } from './imaging/ProgressPanel';
import { PreviewPanel } from './imaging/PreviewPanel';
import { QueuePanel } from './imaging/QueuePanel';
import { useImaging } from './imaging/ImagingProvider';
import type { FileLeaf, MissingRange } from './imaging/types';

const IMAGING_CMD_REGEX = /^(img|cam|lcd)_/;
const ERROR_PTYPES = new Set(['ERR', 'NACK', 'FAIL', 'TIMEOUT']);
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
    selectedStem,
    previewTab,
    previewVersion,
    destNode,
    setSelectedStem,
    setPreviewTab,
    setDestNode,
    refetch,
  } = useImaging();

  // ── TX routing + schema ─────────────────────────────────────────
  const [nodes, setNodes] = useState<string[]>([]);
  const [schema, setSchema] = useState<Record<string, Record<string, unknown>> | null>(null);

  // ── Delete confirm ──────────────────────────────────────────────
  const [deleteTarget, setDeleteTarget] = useState<string[] | null>(null);

  // ── RX log state (imaging-filtered view of shared RX buffer) ────
  const [receiving, setReceiving] = useState(false);
  const receivingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Column defs (shared with main dashboard via SessionProvider) ─
  // Pop-out windows render outside SessionProvider (hasProvider=false) and
  // fall back to local fetches. Main window reads from context.
  const { defs: ctxDefs, hasProvider } = useColumnDefs();
  const [localRxColumns, setLocalRxColumns] = useState<ColumnDef[]>([]);
  const [localTxColumns, setLocalTxColumns] = useState<TxColumnDef[]>([]);
  useEffect(() => {
    if (hasProvider) return;
    fetch('/api/columns').then(r => r.json()).then(setLocalRxColumns).catch(() => {});
    fetch('/api/tx-columns').then(r => r.json()).then(setLocalTxColumns).catch(() => {});
  }, [hasProvider]);
  const rxColumns = ctxDefs?.rx ?? localRxColumns;
  const txColumns = ctxDefs?.tx ?? localTxColumns;

  useEffect(() => {
    fetchSchema().then(setSchema).catch(() => {});
  }, [fetchSchema]);

  const imagingNodeSet = useMemo<Set<string>>(() => {
    const fromSchema = (schema?.img_get_chunks as { nodes?: string[] } | undefined)?.nodes;
    if (fromSchema && fromSchema.length > 0) return new Set(fromSchema);
    return FALLBACK_IMAGING_NODES;
  }, [schema]);

  // Thumbnail-filename prefix, e.g. "tn_". Feeds the FilenameInput tag
  // and the destination-from-filename helper in TxControlsPanel.
  const thumbPrefix =
    (config?.mission.config.imaging as { thumb_prefix?: string } | undefined)?.thumb_prefix ?? '';

  useEffect(() => {
    if (!schema) return;
    const imgCmd = schema?.img_get_chunks ?? schema?.img_cnt_chunks;
    const allowedNodes = ((imgCmd as { nodes?: string[] } | undefined)?.nodes) ?? [];
    const nodeNames = allowedNodes.length > 0 ? allowedNodes : Array.from(FALLBACK_IMAGING_NODES);
    setNodes(nodeNames);
    if (nodeNames.length > 0 && !destNode) setDestNode(nodeNames[0]);
  }, [schema, destNode, setDestNode]);

  useEffect(() => {
    return () => {
      if (receivingTimer.current) clearTimeout(receivingTimer.current);
    };
  }, []);

  // Imaging-filtered RX log — preserves full RxPacket so shared
  // PacketList can render them with the same columns as the main dashboard.
  const imagingPackets = useMemo<RxPacket[]>(() => {
    const rows: RxPacket[] = [];
    for (const p of rxPackets) {
      const cmdRaw = renderingText(p._rendering, 'cmd');
      const ptype = renderingText(p._rendering, 'ptype').toUpperCase();
      const node = renderingText(p._rendering, 'src');
      const isImagingCmd = IMAGING_CMD_REGEX.test(cmdRaw);
      const isImagingError = ERROR_PTYPES.has(ptype) && imagingNodeSet.has(node);
      if (!isImagingCmd && !isImagingError) continue;
      rows.push(p);
    }
    return rows;
  }, [rxPackets, imagingNodeSet]);

  const prevRxCount = useRef(0);
  useEffect(() => {
    if (imagingPackets.length > prevRxCount.current) {
      setReceiving(true);
      if (receivingTimer.current) clearTimeout(receivingTimer.current);
      receivingTimer.current = setTimeout(() => setReceiving(false), 1500);
    }
    prevRxCount.current = imagingPackets.length;
  }, [imagingPackets]);

  const selected = useMemo(
    () => files.find((f) => f.stem === selectedStem) ?? null,
    [files, selectedStem],
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
          dest: destNode,
          echo: ((schema?.img_get_chunks as Record<string, unknown>)?.echo as string) ?? 'NONE',
          ptype: ((schema?.img_get_chunks as Record<string, unknown>)?.ptype as string) ?? 'CMD',
        });
      }
      showToast(
        `Staged ${ranges.length} re-request${ranges.length === 1 ? '' : 's'} (${side})`,
        'success',
        'tx',
      );
    },
    [destNode, queueCommand, schema],
  );

  // Delete every real leaf in a pair (full side and thumb side). After
  // refetch, reset selection if the previously-selected stem no longer
  // exists in the fresh list.
  const performDelete = useCallback(
    (filenames: string[]) => {
      Promise.all(
        filenames.map((fn) =>
          fetch(`/api/plugins/imaging/file/${encodeURIComponent(fn)}`, { method: 'DELETE' })
            .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}: ${fn}`)))),
        ),
      )
        .then(async () => {
          const fresh = await refetch();
          if (!fresh.find((f) => f.stem === selectedStem)) {
            setSelectedStem(fresh[0]?.stem ?? '');
          }
          showToast(`Deleted ${filenames.join(' + ')}`, 'success', 'tx');
        })
        .catch((err) => showToast(`Failed to delete: ${err.message}`, 'error', 'tx'));
    },
    [refetch, selectedStem, setSelectedStem],
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
              destNode={destNode}
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
              onSelect={setSelectedStem}
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
            ? `${deleteTarget.join(' + ')} and all chunks will be removed from disk. This cannot be undone.`
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
