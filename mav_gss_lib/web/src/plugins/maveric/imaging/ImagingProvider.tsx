/**
 * ImagingProvider — root-mounted state for the MAVERIC imaging page.
 *
 * Mission-owned (MAVERIC), mounted at the app root by the platform's
 * MissionProviders wrapper. Subscribes to the `imaging_progress`
 * websocket broadcasts and seeds initial state from
 * /api/plugins/imaging/status so the paired-file view is ready before
 * the Imaging page (or a pop-out) mounts.
 *
 * Why root-level and not inside ImagingPage: the RX socket delivers
 * `imaging_progress` and `on_client_connect` replay messages
 * immediately on connect — a page-local provider would miss anything
 * that fires while the operator is on a different tab. The platform
 * ParametersProvider plays the same root-mount role for live
 * parameter values; this provider mirrors that pattern for imaging
 * progress events.
 *
 * Single-consumer rule: only `ImagingPage.tsx` should call
 * `useImaging()`. It destructures once and passes narrow props to
 * memo'd children.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';
import { useRxStatus } from '@/state/rxHooks';
import { fetchImagingStatus } from './helpers';
import type { PairedFile, ImagingTab } from './types';

interface ImagingProgressMsg {
  type: 'imaging_progress';
  filename: string;
  received: number;
  total: number | null;
  complete: boolean;
}

interface ImagingApi {
  files: PairedFile[];
  selectedStem: string;
  previewTab: ImagingTab;
  previewVersion: number;
  /** Persisted imaging destination node (HLNV / ASTR). Survives
   *  navigation so the operator doesn't re-pick it every time. */
  destNode: string;
  setSelectedStem: (stem: string) => void;
  setPreviewTab: (tab: ImagingTab) => void;
  setDestNode: (n: string) => void;
  refetch: () => Promise<PairedFile[]>;
}

const ImagingContext = createContext<ImagingApi | null>(null);

export function ImagingProvider({ children }: PropsWithChildren) {
  const { subscribeCustom: subscribeRxCustom } = useRxStatus();

  const [files, setFiles] = useState<PairedFile[]>([]);
  const [selectedStem, setSelectedStem] = useState('');
  const [previewTab, setPreviewTab] = useState<ImagingTab>('thumb');
  const [previewVersion, setPreviewVersion] = useState(0);
  const [destNode, setDestNode] = useState('');

  // Ref mirror so the broadcast handler reads current files without
  // becoming a dependency and resubscribing on every change.
  const filesRef = useRef<PairedFile[]>([]);
  useEffect(() => {
    filesRef.current = files;
  }, [files]);

  const refetch = useCallback(async () => {
    const fresh = await fetchImagingStatus();
    setFiles(fresh);
    return fresh;
  }, []);

  // Seed initial state. The on_client_connect replay the backend
  // emits for imaging handles the live per-file progress; this
  // REST fetch gives us the paired-file grouping (thumb/full
  // pairing by prefix) that the broadcast alone can't reconstruct.
  useEffect(() => {
    refetch();
  }, [refetch]);

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
        setSelectedStem(targetPair.stem);
      } else {
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

  const selected = useMemo(
    () => files.find((f) => f.stem === selectedStem) ?? null,
    [files, selectedStem],
  );

  useEffect(() => {
    setPreviewVersion((v) => v + 1);
  }, [selectedStem, selected?.full?.received, selected?.thumb?.received]);

  const api = useMemo<ImagingApi>(
    () => ({
      files,
      selectedStem,
      previewTab,
      previewVersion,
      destNode,
      setSelectedStem,
      setPreviewTab,
      setDestNode,
      refetch,
    }),
    [files, selectedStem, previewTab, previewVersion, destNode, refetch],
  );

  return <ImagingContext.Provider value={api}>{children}</ImagingContext.Provider>;
}

export function useImaging(): ImagingApi {
  const ctx = useContext(ImagingContext);
  if (!ctx) {
    throw new Error(
      'useImaging must be used inside <ImagingProvider>. '
      + 'Check that plugins/maveric/providers.ts registers ImagingProvider.',
    );
  }
  return ctx;
}
