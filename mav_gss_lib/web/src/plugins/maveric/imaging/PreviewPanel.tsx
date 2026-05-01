import { useMemo } from 'react';
import { Image as ImageIcon } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { colors } from '@/lib/colors';
import type { PairedFile, ImagingTab } from './types';
import { imagingFileEndpoint } from './helpers';
import { SourcePill } from './SourcePill';

interface PreviewPanelProps {
  selected: PairedFile | null;
  activeTab: ImagingTab;
  onTabChange: (tab: ImagingTab) => void;
  /** Monotonic version — bumped by parent when chunks arrive so the `<img>` refreshes. */
  version: string | number;
}

/**
 * Preview with [Thumb] [Full] tabs. The active tab selects which
 * filename is fetched from /api/plugins/files/preview?kind=image. If the pair
 * has no thumb side, the tabs are hidden and only the full image is
 * shown. Chunk size and byte count live in the header next to the
 * filename — no separate metadata strip.
 */
export function PreviewPanel({ selected, activeTab, onTabChange, version }: PreviewPanelProps) {
  const leaf = useMemo(() => {
    if (!selected) return null;
    // When one side is null (prefix unset, or orphan pair), fall back
    // to whichever side exists.
    if (!selected.thumb) return selected.full;
    if (!selected.full) return selected.thumb;
    return activeTab === 'thumb' ? selected.thumb : selected.full;
  }, [selected, activeTab]);

  const imgSrc = useMemo(() => {
    if (!leaf) return '';
    const endpoint = imagingFileEndpoint('preview', leaf);
    const sep = endpoint.includes('?') ? '&' : '?';
    return `${endpoint}${sep}v=${encodeURIComponent(String(version))}`;
  }, [leaf, version]);

  const hasThumbSide = !!selected?.thumb;
  const showTabs = hasThumbSide;

  const chunkSize = leaf?.chunk_size ?? 150;
  const bytes = leaf ? leaf.received * chunkSize : 0;

  return (
    <div
      className="rounded-md border overflow-hidden flex flex-col flex-1 min-h-0"
      style={{
        borderColor: colors.borderSubtle,
        backgroundColor: colors.bgPanel,
        boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
      }}
    >
      <div
        className="flex items-center gap-2 px-3 border-b shrink-0"
        style={{
          borderColor: colors.borderSubtle,
          minHeight: 34,
          paddingTop: 6,
          paddingBottom: 6,
        }}
      >
        <ImageIcon className="size-3.5" style={{ color: colors.dim }} />
        <span
          className="font-bold uppercase"
          style={{
            color: colors.value,
            fontSize: 14,
            letterSpacing: '0.02em',
          }}
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
          <div className="ml-1 flex min-w-0 items-center gap-1.5">
            <SourcePill source={leaf.source} />
            <span className="text-[11px] font-mono truncate max-w-[360px]" style={{ color: colors.dim }}>
              {leaf.filename}
            </span>
          </div>
        )}
        <div className="flex-1" />
        {leaf && leaf.total !== null && (
          <span className="text-[10px] font-mono" style={{ color: colors.dim }}>
            {chunkSize} B/chunk · {(bytes / 1024).toFixed(1)} KB
          </span>
        )}
      </div>

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
    </div>
  );
}
