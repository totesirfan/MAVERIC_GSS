/**
 * Shared types for the file-chunk subsystem.
 *
 * Names match Python: same concept, one name across the stack.
 */

export type FileKind = 'image' | 'aii' | 'mag';

export interface FileLeaf {
  id: string;
  kind: FileKind;
  source: string | null;
  filename: string;
  received: number;
  total: number | null;
  complete: boolean;
  chunk_size: number | null;
  last_activity_ms?: number | null;
  valid?: boolean | null;  // aii only
}

export interface ImagePair {
  id: string;
  kind: 'image';
  source: string | null;
  stem: string;
  full: FileLeaf;
  thumb: FileLeaf | null;
  last_activity_ms: number | null;
}

export interface ImageStatusResponse {
  files: ImagePair[];
}

export interface FlatStatusResponse {
  files: FileLeaf[];
}

export interface FileProgressMessage {
  type: 'file_progress';
  kind: FileKind;
  source: string | null;
  id: string;
  filename: string;
  received: number;
  total: number | null;
  complete: boolean;
  valid?: boolean | null;
}

export interface MissingRange {
  start: number;
  end: number;
  count: number;
}

export type ImagingTab = 'thumb' | 'full';
