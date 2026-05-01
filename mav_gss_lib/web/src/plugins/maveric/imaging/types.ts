// Imaging UI types are the same shape as the shared FileChunk types.
// Legacy name `PairedFile` is preserved as an alias of `ImagePair`
// so existing consumers (PreviewPanel, ProgressPanel, ImagingPage)
// continue to compile without per-file rewrites.
import type { ImagePair } from '../files/types';

export type PairedFile = ImagePair;
export type {
  FileKind,
  FileLeaf,
  ImageStatusResponse,
  ImagingTab,
  MissingRange,
} from '../files/types';
