import { createContext, useContext } from 'react';
import type { PairedFile, ImagingTab } from './types';

export interface ImagingApi {
  files: PairedFile[];
  selectedStem: string;
  previewTab: ImagingTab;
  previewVersion: string;
  /** Persisted imaging destination node (HLNV / ASTR). Survives
   *  navigation so the operator doesn't re-pick it every time. */
  destNode: string;
  setSelectedStem: (stem: string) => void;
  setPreviewTab: (tab: ImagingTab) => void;
  setDestNode: (n: string) => void;
  refetch: () => Promise<PairedFile[]>;
}

export const ImagingContext = createContext<ImagingApi | null>(null);

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
