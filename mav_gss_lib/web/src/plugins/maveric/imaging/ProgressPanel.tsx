import { useMemo, useState, useEffect } from 'react';
import { Grid3x3, ChevronDown, Trash2, RefreshCcw, Download } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { colors } from '@/lib/colors';
import {
  computeMissingRanges,
  formatMissingRanges,
  type PairedFile,
  type FileLeaf,
  type MissingRange,
} from './helpers';

type Side = 'thumb' | 'full';

interface ProgressPanelProps {
  files: PairedFile[];
  selected: PairedFile | null;
  onSelect: (stem: string) => void;
  /** Delete every real leaf in the selected pair. Placeholder leaves
   *  (total === null) are skipped — there's no file on disk to delete. */
  onDelete: (filenames: string[]) => void;
  /** Stage contiguous re-request commands for a specific side. */
  onStageRerequest: (side: Side, leaf: FileLeaf, ranges: MissingRange[]) => void;
}

interface ChunkSetByFilename {
  [filename: string]: Set<number>;
}

/**
 * File selector + stacked per-side progress rows with clickable missing
 * chunks. Auto-routes target per grid: thumb grid stages with thumb
 * filename, full grid stages with full filename. Route (HLNV/ASTR)
 * respects whatever the operator has set globally — not auto-overridden.
 */
export function ProgressPanel({
  files,
  selected,
  onSelect,
  onDelete,
  onStageRerequest,
}: ProgressPanelProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  // Fetch per-chunk state for whichever leaves are present in the selected pair.
  const [chunkSets, setChunkSets] = useState<ChunkSetByFilename>({});

  useEffect(() => {
    if (!selected) {
      setChunkSets({});
      return;
    }
    const toFetch = [selected.full, selected.thumb].filter(
      (l): l is FileLeaf => l !== null && l.total !== null,
    );
    const ctrl = new AbortController();
    Promise.all(
      toFetch.map(leaf =>
        fetch(`/api/plugins/imaging/chunks/${encodeURIComponent(leaf.filename)}`, {
          signal: ctrl.signal,
        })
          .then(r => r.json())
          .then(data => [leaf.filename, new Set<number>(data.chunks ?? [])] as const)
          .catch(() => [leaf.filename, new Set<number>()] as const),
      ),
    ).then(pairs => {
      const next: ChunkSetByFilename = {};
      for (const [fn, s] of pairs) next[fn] = s;
      setChunkSets(next);
    });
    return () => ctrl.abort();
  }, [
    selected?.stem,
    selected?.full?.received,
    selected?.thumb?.received,
  ]);

  return (
    <div
      className="rounded-lg border overflow-hidden shrink-0"
      style={{
        borderColor: colors.borderSubtle,
        backgroundColor: colors.bgPanel,
        boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
      }}
    >
      <div
        className="flex items-center gap-2 px-3 py-1.5 border-b"
        style={{ borderColor: colors.borderSubtle }}
      >
        <Grid3x3 className="size-3.5" style={{ color: colors.dim }} />
        <span
          className="text-[11px] font-bold uppercase tracking-wider"
          style={{ color: colors.value }}
        >
          Progress
        </span>
        <div className="flex-1" />
        {files.length > 0 && (
          <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
            <PopoverTrigger
              className="flex items-center gap-1.5 border rounded px-2 py-0.5 text-[11px] font-mono text-fg hover:bg-white/[0.04] outline-none transition-colors"
              style={{ borderColor: colors.borderSubtle }}
            >
              {selected?.stem ?? 'Select file'}
              <ChevronDown className="size-3" style={{ color: colors.dim }} />
            </PopoverTrigger>
            <PopoverContent align="end" className="p-0 w-[320px]">
              <Command>
                <CommandInput placeholder="Search filename..." className="h-8 text-[11px]" />
                <CommandList>
                  <CommandEmpty className="py-4 text-center text-[11px]" style={{ color: colors.dim }}>
                    No files
                  </CommandEmpty>
                  <CommandGroup>
                    {files.map(p => (
                      <CommandItem
                        key={p.stem}
                        value={p.stem}
                        onSelect={() => {
                          onSelect(p.stem);
                          setPickerOpen(false);
                        }}
                        className="text-[11px] font-mono"
                      >
                        <span className="flex-1 truncate">{p.stem}</span>
                        <LeafState leaf={p.thumb} label="thumb" />
                        <LeafState leaf={p.full} label="full" />
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
        )}
        {selected && (() => {
          const realFiles: string[] = [];
          if (selected.full && selected.full.total !== null) realFiles.push(selected.full.filename);
          if (selected.thumb && selected.thumb.total !== null) realFiles.push(selected.thumb.filename);
          if (realFiles.length === 0) return null;
          return (
            <button
              onClick={() => onDelete(realFiles)}
              className="p-1 rounded border hover:bg-white/[0.04]"
              style={{ borderColor: colors.borderSubtle }}
              title={`Delete ${realFiles.join(' + ')}`}
            >
              <Trash2 className="size-3" style={{ color: colors.danger }} />
            </button>
          );
        })()}
      </div>

      {selected ? (
        <div className="px-4 py-3 space-y-4">
          {selected.thumb && (
            <ProgressRow
              side="thumb"
              leaf={selected.thumb}
              chunkSet={chunkSets[selected.thumb.filename] ?? new Set()}
              onStageRerequest={onStageRerequest}
            />
          )}
          {selected.full && (
            <ProgressRow
              side="full"
              leaf={selected.full}
              chunkSet={chunkSets[selected.full.filename] ?? new Set()}
              onStageRerequest={onStageRerequest}
            />
          )}
        </div>
      ) : (
        <div className="px-3 py-3 text-[11px]" style={{ color: colors.dim }}>
          {files.length === 0 ? 'No active transfers' : 'Select a file to view progress'}
        </div>
      )}
    </div>
  );
}

function LeafState({ leaf, label }: { leaf: FileLeaf | null; label: string }) {
  if (!leaf) return null;
  const complete = leaf.total !== null && leaf.received === leaf.total;
  const stateText =
    leaf.total === null
      ? `${label}: ?`
      : complete
      ? `${label} ✓`
      : `${label} ${leaf.received}/${leaf.total}`;
  return (
    <span
      className="text-[10px] ml-2"
      style={{ color: complete ? colors.success : colors.dim }}
    >
      {stateText}
    </span>
  );
}

function ProgressRow({
  side,
  leaf,
  chunkSet,
  onStageRerequest,
}: {
  side: Side;
  leaf: FileLeaf;
  chunkSet: Set<number>;
  onStageRerequest: ProgressPanelProps['onStageRerequest'];
}) {
  const ranges = useMemo(() => computeMissingRanges(leaf.total, chunkSet), [leaf.total, chunkSet]);
  const total = leaf.total ?? 0;
  const pct = total > 0 ? Math.round((leaf.received / total) * 100) : 0;
  const complete = total > 0 && leaf.received === total;

  if (leaf.total === null) {
    return (
      <div>
        <div className="text-[10px] uppercase tracking-wider font-bold mb-1" style={{ color: colors.dim }}>
          {side}
        </div>
        <div className="text-[11px]" style={{ color: colors.dim }}>
          Not counted
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-1.5">
        <span
          className="text-[10px] uppercase tracking-wider font-bold"
          style={{ color: colors.dim }}
        >
          {side}
        </span>
        <span className="text-[11px] font-semibold font-mono" style={{ color: colors.value }}>
          {leaf.received} / {total}
        </span>
        <span className="text-[11px]" style={{ color: colors.dim }}>
          ({pct}%)
        </span>
        <div className="flex-1" />
        <span
          className="text-[11px]"
          style={{
            color: complete
              ? colors.success
              : ranges.length
              ? colors.warning
              : colors.active,
          }}
        >
          {complete ? 'Complete' : ranges.length ? `${total - leaf.received} missing` : 'Receiving...'}
        </span>
      </div>

      <div className="flex flex-wrap gap-[3px] mb-2">
        {Array.from({ length: total }, (_, i) => {
          const received = chunkSet.has(i);
          return (
            <button
              key={i}
              disabled={received}
              onClick={() =>
                onStageRerequest(side, leaf, [{ start: i, end: i, count: 1 }])
              }
              title={received ? `Chunk ${i}` : `Chunk ${i} (click to re-request)`}
              className="rounded-full"
              style={{
                width: 8,
                height: 8,
                backgroundColor: received ? colors.success : 'transparent',
                border: received ? 'none' : `1px solid ${colors.danger}`,
                cursor: received ? 'default' : 'pointer',
                boxSizing: 'border-box',
                padding: 0,
              }}
            />
          );
        })}
      </div>

      {!complete && leaf.received === 0 && total > 0 && (
        <div
          className="flex items-center pt-2 border-t"
          style={{ borderColor: colors.borderSubtle }}
        >
          <div className="flex-1" />
          <button
            onClick={() => onStageRerequest(side, leaf, ranges)}
            className="inline-flex items-center gap-1 px-2 rounded-sm border font-medium text-[10px]"
            style={{
              height: 22,
              color: colors.label,
              borderColor: `${colors.label}66`,
              backgroundColor: `${colors.label}0A`,
            }}
          >
            <Download className="size-3" /> Request chunks ({total})
          </button>
        </div>
      )}

      {!complete && leaf.received > 0 && ranges.length > 0 && (
        <div
          className="flex items-center flex-wrap gap-1.5 pt-2 border-t"
          style={{ borderColor: colors.borderSubtle }}
        >
          <span
            className="text-[10px] font-bold uppercase tracking-wider mr-1"
            style={{ color: colors.danger }}
          >
            Missing
          </span>
          {formatMissingRanges(ranges).map((label, i) => (
            <button
              key={i}
              onClick={() => onStageRerequest(side, leaf, [ranges[i]])}
              className="inline-flex items-center gap-1 px-1.5 rounded-sm border font-mono text-[11px]"
              style={{
                height: 18,
                color: colors.danger,
                borderColor: `${colors.danger}66`,
                backgroundColor: `${colors.danger}0A`,
              }}
            >
              <RefreshCcw className="size-2.5" />
              {label}
            </button>
          ))}
          <button
            onClick={() => onStageRerequest(side, leaf, ranges)}
            className="ml-auto inline-flex items-center gap-1 px-2 rounded-sm border font-medium text-[10px]"
            style={{
              height: 22,
              color: colors.warning,
              borderColor: `${colors.warning}66`,
              backgroundColor: `${colors.warning}0A`,
            }}
          >
            <RefreshCcw className="size-3" /> Re-request all ({ranges.length})
          </button>
        </div>
      )}
    </div>
  );
}
