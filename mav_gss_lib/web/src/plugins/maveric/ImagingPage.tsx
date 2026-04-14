import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { ConfirmDialog } from '@/components/shared/ConfirmDialog';
import { showToast } from '@/components/shared/StatusToast';
import { usePluginServices } from '@/hooks/usePluginServices';

import { RxLogPanel, type ImagingLogRow } from './imaging/RxLogPanel';
import { TxControlsPanel } from './imaging/TxControlsPanel';
import { ProgressPanel } from './imaging/ProgressPanel';
import { PreviewPanel } from './imaging/PreviewPanel';
import { QueuePanel } from './imaging/QueuePanel';
import { fetchImagingStatus, DEFAULT_TARGET_ARG } from './imaging/helpers';
import type { PairedFile, FileLeaf, ImagingTab, MissingRange } from './imaging/types';

const IMAGING_CMD_REGEX = /^(img|cam)_/;
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
    sessionResetGen,
    fetchSchema,
    sendAll,
    abortSend,
    sendProgress,
    pendingQueue,
    removeQueueItem,
  } = usePluginServices();

  // ── Paired file state ───────────────────────────────────────────
  const [files, setFiles] = useState<PairedFile[]>([]);
  const [selectedStem, setSelectedStem] = useState<string>('');
  const [previewTab, setPreviewTab] = useState<ImagingTab>('thumb');

  // ── TX routing + schema ─────────────────────────────────────────
  const [destNode, setDestNode] = useState('');
  const [targetArg, setTargetArg] = useState(DEFAULT_TARGET_ARG); // '2' = thumb, per thumb-first workflow
  const [nodes, setNodes] = useState<string[]>([]);
  const [schema, setSchema] = useState<Record<string, Record<string, unknown>> | null>(null);

  // ── Delete confirm ──────────────────────────────────────────────
  const [deleteTarget, setDeleteTarget] = useState<string[] | null>(null);

  // ── RX log state (imaging-filtered view of shared RX buffer) ────
  const [rxRows, setRxRows] = useState<ImagingLogRow[]>([]);
  const [receiving, setReceiving] = useState(false);
  const receivingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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
    fetchImagingStatus().then((f) => {
      if (cancelled) return;
      setFiles(f);
      if (f.length > 0) setSelectedStem((prev) => prev || f[0].stem);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Session reset — only refires on *actual* changes after mount
  const mountResetGen = useRef(sessionResetGen);
  useEffect(() => {
    if (sessionResetGen === mountResetGen.current) return;
    setRxRows([]);
    setReceiving(false);
    setFiles([]);
    setSelectedStem('');
    fetchImagingStatus().then((f) => {
      setFiles(f);
      if (f.length > 0) setSelectedStem(f[0].stem);
    });
  }, [sessionResetGen]);

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
        // Auto-select only when the operator has no selection at all, or
        // when the current selection no longer exists in the file list.
        // Never stomp an intentional selection with a live chunk update
        // from a different file.
        setSelectedStem((prev) => {
          if (!prev) return targetPair.stem;
          const prevExists = snapshot.some((p) => p.stem === prev);
          return prevExists ? prev : targetPair.stem;
        });
      } else {
        // Unknown filename — rare path (first touch of a scheduled-capture
        // recovery file). Full refetch. Only auto-select if the operator
        // has no current selection.
        fetchImagingStatus().then((fresh) => {
          setFiles(fresh);
          setSelectedStem((prev) => {
            if (prev) return prev;
            const match = fresh.find(
              (p) => p.full?.filename === fn || p.thumb?.filename === fn,
            );
            return match ? match.stem : prev;
          });
        });
      }
    });
  }, [subscribeRxCustom]);

  // Imaging-filtered RX log
  const imagingPackets = useMemo<ImagingLogRow[]>(() => {
    const rows: ImagingLogRow[] = [];
    for (const p of rxPackets) {
      const cmdRaw = String(p._rendering?.row?.values?.cmd ?? '');
      const ptype = String(p._rendering?.row?.values?.ptype ?? '').toUpperCase();
      const node = String(p._rendering?.row?.values?.src ?? '');
      const isImagingCmd = IMAGING_CMD_REGEX.test(cmdRaw);
      const isImagingError = ERROR_PTYPES.has(ptype) && imagingNodeSet.has(node);
      if (!isImagingCmd && !isImagingError) continue;
      const parts = cmdRaw.split(' ');
      rows.push({
        num: p.num,
        time: p.time,
        cmd: parts[0] ?? '',
        args: parts.slice(1).join(' '),
      });
    }
    return rows;
  }, [rxPackets, imagingNodeSet]);

  const prevRxCount = useRef(0);
  useEffect(() => {
    if (imagingPackets.length > prevRxCount.current) {
      setRxRows(imagingPackets.slice(-500));
      setReceiving(true);
      if (receivingTimer.current) clearTimeout(receivingTimer.current);
      receivingTimer.current = setTimeout(() => setReceiving(false), 1500);
    }
    prevRxCount.current = imagingPackets.length;
  }, [imagingPackets]);

  // Selected pair + preview version bump on progress
  const selected = useMemo(
    () => files.find((f) => f.stem === selectedStem) ?? null,
    [files, selectedStem],
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
        });
        showToast(`Deleted ${filenames.join(' + ')}`, 'success', 'tx');
      })
      .catch((err) => showToast(`Failed to delete: ${err.message}`, 'error', 'tx'));
  }, []);

  return (
    <div className="flex-1 flex overflow-hidden p-4 gap-4">
      {/* Left column — fixed 560px width (SplitPane integration deferred) */}
      <div className="flex flex-col gap-4 shrink-0" style={{ width: 560 }}>
        {/* RX Log — wrapper pins it to 200px so the internal flex-1 fills it */}
        <div className="h-[200px] shrink-0 flex flex-col">
          <RxLogPanel packets={rxRows} receiving={receiving} />
        </div>
        <TxControlsPanel
          nodes={nodes}
          destNode={destNode}
          onDestNodeChange={setDestNode}
          targetArg={targetArg}
          onTargetChange={setTargetArg}
          selected={selected}
          previewTab={previewTab}
          queueCommand={queueCommand}
          schema={schema}
          txConnected={txConnected}
        />
        <QueuePanel
          pendingQueue={pendingQueue}
          sendProgress={sendProgress}
          sendAll={sendAll}
          abortSend={abortSend}
          removeQueueItem={removeQueueItem}
        />
      </div>

      {/* Right column */}
      <div className="flex-1 flex flex-col gap-4 min-w-0">
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
