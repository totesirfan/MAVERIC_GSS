import { useMemo, useState } from 'react';
import { Image as ImageIcon, Expand, X } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { colors } from '@/lib/colors';
import type { PairedFile, ImagingTab } from './types';

interface PreviewPanelProps {
  selected: PairedFile | null;
  activeTab: ImagingTab;
  onTabChange: (tab: ImagingTab) => void;
  /** Monotonic version — bumped by parent when chunks arrive so the `<img>` refreshes. */
  version: number;
}

/**
 * Preview with [Thumb] [Full] tabs. The active tab selects which
 * filename is fetched from /api/plugins/imaging/preview. If the pair
 * has no thumb side (`pair.thumb === null`, i.e. prefix unset or
 * orphan), the tabs are hidden and only the full image is shown.
 */
export function PreviewPanel({ selected, activeTab, onTabChange, version }: PreviewPanelProps) {
  const [modalOpen, setModalOpen] = useState(false);

  const leaf = useMemo(() => {
    if (!selected) return null;
    // When one side is null (prefix unset, or orphan pair that the backend
    // happened to produce), fall back to whichever side exists.
    if (!selected.thumb) return selected.full;
    if (!selected.full) return selected.thumb;
    return activeTab === 'thumb' ? selected.thumb : selected.full;
  }, [selected, activeTab]);

  const imgSrc = useMemo(() => {
    if (!leaf) return '';
    return `/api/plugins/imaging/preview/${encodeURIComponent(leaf.filename)}?v=${version}`;
  }, [leaf, version]);

  const hasThumbSide = !!selected?.thumb;
  const showTabs = hasThumbSide; // Single-file entries (no thumb) hide tabs entirely.

  const chunkSize = leaf?.chunk_size ?? 150;
  const bytes = leaf ? leaf.received * chunkSize : 0;

  return (
    <div
      className="rounded-lg border overflow-hidden flex flex-col flex-1 min-h-0"
      style={{
        borderColor: colors.borderSubtle,
        backgroundColor: colors.bgPanel,
        boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
      }}
    >
      <div
        className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0"
        style={{ borderColor: colors.borderSubtle }}
      >
        <ImageIcon className="size-3.5" style={{ color: colors.dim }} />
        <span
          className="text-[11px] font-bold uppercase tracking-wider"
          style={{ color: colors.value }}
        >
          Preview
        </span>
        {showTabs && (
          <Tabs value={activeTab} onValueChange={(v) => onTabChange(v as ImagingTab)}>
            <TabsList className="h-6">
              <TabsTrigger value="thumb" className="text-[10px] px-2 py-0">Thumb</TabsTrigger>
              <TabsTrigger value="full" className="text-[10px] px-2 py-0">Full</TabsTrigger>
            </TabsList>
          </Tabs>
        )}
        {leaf && (
          <span className="text-[11px] font-mono ml-1" style={{ color: colors.dim }}>
            {leaf.filename}
          </span>
        )}
        <div className="flex-1" />
        <button
          onClick={() => setModalOpen(true)}
          className="p-1 rounded hover:bg-white/[0.03]"
          aria-label="Fullscreen"
          disabled={!leaf}
        >
          <Expand className="size-3.5" style={{ color: colors.dim }} />
        </button>
      </div>

      {/* Metadata strip — derive the side label from the actual leaf
           being displayed, not from activeTab. The leaf cascade can fall
           back to the opposite side when one is missing, in which case
           activeTab may not match what's on screen. */}
      {leaf && (
        <div
          className="px-4 py-1.5 border-b font-mono text-[10px] flex items-center gap-3 flex-wrap"
          style={{ borderColor: colors.borderSubtle, color: colors.dim }}
        >
          <span style={{ color: colors.value }}>
            {selected?.thumb?.filename === leaf.filename ? 'thumb' : 'full'}
          </span>
          <span style={{ color: colors.borderStrong }}>·</span>
          <span>{chunkSize} B/chunk</span>
          <span style={{ color: colors.borderStrong }}>·</span>
          <span>{(bytes / 1024).toFixed(1)} KB</span>
        </div>
      )}

      {/* Image area */}
      <div className="flex-1 min-h-0 p-4 relative">
        {leaf && leaf.total !== null ? (
          <img
            src={imgSrc}
            alt={leaf.filename}
            className="absolute inset-4 w-[calc(100%-2rem)] h-[calc(100%-2rem)] object-contain"
            onError={() => {}}
          />
        ) : (
          <div
            className="absolute inset-0 flex items-center justify-center text-[11px] px-6 text-center"
            style={{ color: colors.dim }}
          >
            {!selected ? 'Select a file to preview' : 'No data'}
          </div>
        )}
      </div>

      {/* Fullscreen modal */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="max-w-[90vw] max-h-[90vh] p-6">
          <div className="flex items-center gap-2 mb-3">
            <ImageIcon className="size-4" style={{ color: colors.active }} />
            <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.value }}>
              Preview
            </span>
            {leaf && (
              <span className="text-xs font-mono" style={{ color: colors.dim }}>
                {leaf.filename}
              </span>
            )}
            <div className="flex-1" />
            <button
              onClick={() => setModalOpen(false)}
              className="p-1 rounded hover:bg-white/[0.04]"
              aria-label="Close"
            >
              <X className="size-4" style={{ color: colors.dim }} />
            </button>
          </div>
          <div className="flex items-center justify-center min-h-[60vh]">
            {imgSrc && (
              <img
                src={imgSrc}
                alt={leaf?.filename ?? ''}
                className="max-w-full max-h-[70vh] object-contain"
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
