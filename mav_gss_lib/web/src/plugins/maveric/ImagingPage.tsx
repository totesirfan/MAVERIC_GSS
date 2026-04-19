import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';
import { showToast } from '@/components/shared/StatusToast';
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from '@/components/ui/resizable';
import { usePluginServices } from '@/hooks/usePluginServices';
import { useColumnDefs } from '@/state/session';
import type { ColumnDef, RxPacket, TxColumnDef } from '@/lib/types';

import { RxLogPanel } from './imaging/RxLogPanel';
import { TxControlsPanel } from './imaging/TxControlsPanel';
import { ProgressPanel } from './imaging/ProgressPanel';
import { PreviewPanel } from './imaging/PreviewPanel';
import { QueuePanel } from './imaging/QueuePanel';
import { fetchImagingStatus, DEFAULT_TARGET_ARG } from './imaging/helpers';
import type { PairedFile, FileLeaf, ImagingTab, MissingRange } from './imaging/types';

const IMAGING_CMD_REGEX = /^(img|cam|lcd)_/;
const ERROR_PTYPES = new Set(['ERR', 'NACK', 'FAIL', 'TIMEOUT']);
const FALLBACK_IMAGING_NODES = new Set(['HLNV', 'ASTR']);

interface ImagingProgressMsg {
  type: 'imaging_progress';
  filename: string;
  received: number;
  total: number | null;
  complete: boolean;
}

export default function ImagingPage() {
  const {
    packets: rxPackets,
    config,
    queueCommand,
    txConnected,
    subscribeRxCustom,
    fetchSchema,
    sendAll,
    abortSend,
    sendProgress,
    pendingQueue,
    removeQueueItem,
  } = usePluginServices();

  // ── Paired file state ───────────────────────────────────────────
  const [files, setFiles] = useState<PairedFile[]>([]);
  /** What the Progress + Preview panels display. Auto-switches to
   *  whichever file is actively downloading when chunks arrive. */
  const [selectedStem, setSelectedStem] = useState<string>('');
  /** What the TX Controls auto-fill pulls from. Only changes when the
   *  operator picks a file from the Progress dropdown — never follows
   *  live downloads, and never populates from legacy files on mount. */
  const [userSelectedStem, setUserSelectedStem] = useState<string>('');
  const [previewTab, setPreviewTab] = useState<ImagingTab>('thumb');

  // ── TX routing + schema ─────────────────────────────────────────
  const [destNode, setDestNode] = useState('');
  const [targetArg, setTargetArg] = useState(DEFAULT_TARGET_ARG); // '2' = thumb, per thumb-first workflow
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

  // ── Preview refresh version ─────────────────────────────────────
  const [previewVersion, setPreviewVersion] = useState(0);

  // Schema fetch
  useEffect(() => {
    fetchSchema().then(setSchema).catch(() => {});
  }, [fetchSchema]);

  // Derive imaging-capable routing nodes from schema (not hardcoded)
  const imagingNodeSet = useMemo<Set<string>>(() => {
    const fromSchema = (schema?.img_get_chunk as { nodes?: string[] } | undefined)?.nodes;
    if (fromSchema && fromSchema.length > 0) return new Set(fromSchema);
    return FALLBACK_IMAGING_NODES;
  }, [schema]);

  useEffect(() => {
    if (!config || !schema) return;
    const imgCmd = schema?.img_get_chunk ?? schema?.img_cnt_chunks;
    const allowedNodes: string[] = ((imgCmd as { nodes?: string[] } | undefined)?.nodes) ?? [];
    const nodeMap: Record<string, string> = config?.nodes ?? {};
    let nodeNames: string[];
    if (allowedNodes.length > 0) {
      nodeNames = allowedNodes.filter((n) => Object.values(nodeMap).includes(n));
    } else {
      const gsNode = config?.general?.gs_node ?? '';
      nodeNames = Object.values(nodeMap).filter((n): n is string => n !== gsNode);
    }
    setNodes(nodeNames);
    if (nodeNames.length > 0) setDestNode((prev) => prev || nodeNames[0]);
  }, [config, schema]);

  // Initial status fetch
  useEffect(() => {
    let cancelled = false;
    // Don't auto-select on mount — legacy files on disk shouldn't
    // auto-populate the TxControls filename inputs. Operator picks a
    // file when they want to interact with one.
    fetchImagingStatus().then((f) => {
      if (cancelled) return;
      setFiles(f);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (receivingTimer.current) clearTimeout(receivingTimer.current);
    };
  }, []);

  // Keep a ref to the latest files so the broadcast handler can read
  // them without depending on a closure that React would replace each
  // render. Updated whenever files changes.
  const filesRef = useRef<PairedFile[]>([]);
  useEffect(() => {
    filesRef.current = files;
  }, [files]);

  // ── Merge imaging_progress broadcasts into local state ─────────
  // Do NOT refetch the full status on every chunk — the backend broadcasts
  // one progress message per chunk during a live pass. Instead, find the
  // matching pair + leaf and patch its fields in place. Snapshot filesRef
  // at the top of the handler so auto-select uses a consistent view.
  useEffect(() => {
    return subscribeRxCustom((msg) => {
      if (msg.type !== 'imaging_progress') return;
      const progress = msg as unknown as ImagingProgressMsg;
      const fn = progress.filename;
      if (!fn) return;

      const snapshot = filesRef.current;
      const targetPair = snapshot.find(
        (p) => p.full?.filename === fn || p.thumb?.filename === fn,
      );

      if (targetPair) {
        // Known pair — patch the matching leaf in place.
        setFiles((prev) => {
          const idx = prev.findIndex((p) => p.stem === targetPair.stem);
          if (idx < 0) return prev;
          const pair = prev[idx];
          const nextPair: PairedFile = { ...pair };
          if (pair.full?.filename === fn) {
            nextPair.full = {
              ...pair.full,
              received: progress.received,
              total: progress.total ?? pair.full.total,
              complete: progress.complete,
            };
          } else if (pair.thumb?.filename === fn) {
            nextPair.thumb = {
              ...pair.thumb,
              received: progress.received,
              total: progress.total ?? pair.thumb.total,
              complete: progress.complete,
            };
          }
          const next = [...prev];
          next[idx] = nextPair;
          return next;
        });
        // Always auto-switch display selection to whichever file is
        // actively downloading. Progress + Preview follow live chunks.
        // (TX Controls auto-fill uses userSelectedStem instead, so
        // manual form state is NOT affected by this switch.)
        setSelectedStem(targetPair.stem);
      } else {
        // Unknown filename — rare path (first touch of a scheduled-capture
        // recovery file). Full refetch, then auto-switch display selection
        // to the new entry.
        fetchImagingStatus().then((fresh) => {
          setFiles(fresh);
          const match = fresh.find(
            (p) => p.full?.filename === fn || p.thumb?.filename === fn,
          );
          if (match) setSelectedStem(match.stem);
        });
      }
    });
  }, [subscribeRxCustom]);

  // Imaging-filtered RX log — preserves full RxPacket so shared
  // PacketList can render them with the same columns as the main dashboard.
  const imagingPackets = useMemo<RxPacket[]>(() => {
    const rows: RxPacket[] = [];
    for (const p of rxPackets) {
      const cmdRaw = String(p._rendering?.row?.values?.cmd ?? '');
      const ptype = String(p._rendering?.row?.values?.ptype ?? '').toUpperCase();
      const node = String(p._rendering?.row?.values?.src ?? '');
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

  // Display selection — follows live downloads via the broadcast merge.
  const selected = useMemo(
    () => files.find((f) => f.stem === selectedStem) ?? null,
    [files, selectedStem],
  );

  // TX Controls auto-fill source — only changes when the operator picks
  // a file from the Progress dropdown. Null until that happens, so the
  // form inputs stay empty on mount and during passive live downloads.
  const userSelected = useMemo(
    () => (userSelectedStem ? files.find((f) => f.stem === userSelectedStem) ?? null : null),
    [files, userSelectedStem],
  );

  useEffect(() => {
    setPreviewVersion((v) => v + 1);
  }, [selectedStem, selected?.full?.received, selected?.thumb?.received]);

  // Stage re-request — auto-routes target per side
  const stageRerequest = useCallback(
    (side: 'thumb' | 'full', leaf: FileLeaf, ranges: MissingRange[]) => {
      const forcedTarget = side === 'thumb' ? '2' : '1';
      for (const r of ranges) {
        queueCommand({
          cmd_id: 'img_get_chunk',
          args: {
            Filename: leaf.filename,
            'Start Chunk': String(r.start),
            'Num Chunks': String(r.count),
            Destination: forcedTarget,
          },
          dest: destNode,
          echo: ((schema?.img_get_chunk as Record<string, unknown>)?.echo as string) ?? 'NONE',
          ptype: ((schema?.img_get_chunk as Record<string, unknown>)?.ptype as string) ?? 'CMD',
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
  const performDelete = useCallback((filenames: string[]) => {
    Promise.all(
      filenames.map((fn) =>
        fetch(`/api/plugins/imaging/file/${encodeURIComponent(fn)}`, { method: 'DELETE' })
          .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}: ${fn}`)))),
      ),
    )
      .then(() => {
        fetchImagingStatus().then((fresh) => {
          setFiles(fresh);
          setSelectedStem((prev) =>
            fresh.find((f) => f.stem === prev) ? prev : (fresh[0]?.stem ?? ''),
          );
          setUserSelectedStem((prev) =>
            fresh.find((f) => f.stem === prev) ? prev : '',
          );
        });
        showToast(`Deleted ${filenames.join(' + ')}`, 'success', 'tx');
      })
      .catch((err) => showToast(`Failed to delete: ${err.message}`, 'error', 'tx'));
  }, []);

  return (
    <div className="flex-1 flex overflow-hidden p-4">
      <ResizablePanelGroup className="flex-1 h-full">
        <ResizablePanel defaultSize={42} minSize={25}>
          <div className="flex flex-col gap-4 h-full min-w-0">
            {/* RX Log — wrapper pins it to 200px so the internal flex-1 fills it */}
            <div className="h-[200px] shrink-0 flex flex-col">
              <RxLogPanel packets={imagingPackets} columns={rxColumns} receiving={receiving} />
            </div>
            <TxControlsPanel
              nodes={nodes}
              destNode={destNode}
              onDestNodeChange={setDestNode}
              targetArg={targetArg}
              onTargetChange={setTargetArg}
              selected={userSelected}
              previewTab={previewTab}
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
          className="mx-2 w-1 rounded-full bg-transparent hover:bg-[#222222] data-[resize-handle-active]:bg-[#30C8E0] transition-colors"
        />
        <ResizablePanel defaultSize={58} minSize={25}>
          <div className="flex flex-col gap-4 h-full min-w-0">
            <ProgressPanel
              files={files}
              selected={selected}
              onSelect={(stem) => {
                // Dropdown pick updates BOTH display and TxControls auto-fill.
                setSelectedStem(stem);
                setUserSelectedStem(stem);
              }}
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
