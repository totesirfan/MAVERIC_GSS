import { useMemo } from 'react';
import { ListChecks, Send, X, StopCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { colors } from '@/lib/colors';
import type { TxQueueItem, TxQueueCmd, SendProgress } from '@/lib/types';

interface QueuePanelProps {
  pendingQueue: TxQueueItem[];
  sendProgress: SendProgress | null;
  sendAll: () => void;
  abortSend: () => void;
  removeQueueItem: (index: number) => void;
}

interface ImagingRow {
  /** Index in the unfiltered pendingQueue — required for removeQueueItem */
  absoluteIndex: number;
  item: TxQueueCmd;
  cmdId: string;
  destLabel: string;
  label: string;
}

/**
 * Imaging Queue — filtered, read-only view of the main TX pending queue
 * showing only img_* and cam_* commands. Send all fires the full main
 * queue exactly as the main TxPanel does; a footer hint warns when
 * non-imaging commands would also be sent so the click is never silent.
 */
export function QueuePanel({
  pendingQueue,
  sendProgress,
  sendAll,
  abortSend,
  removeQueueItem,
}: QueuePanelProps) {
  const imagingRows = useMemo<ImagingRow[]>(() => {
    const rows: ImagingRow[] = [];
    pendingQueue.forEach((item, idx) => {
      if (item.type !== 'mission_cmd') return;
      const payload = item.payload as Record<string, unknown>;
      const cmdId = String(payload.cmd_id ?? '');
      if (!/^(img|cam)_/.test(cmdId)) return;
      rows.push({
        absoluteIndex: idx,
        item,
        cmdId,
        destLabel: String(payload.dest ?? ''),
        label: describeCmd(cmdId, payload.args as Record<string, string> | undefined, item),
      });
    });
    return rows;
  }, [pendingQueue]);

  const otherCount = pendingQueue.length - imagingRows.length;
  const sending = !!sendProgress;
  const count = imagingRows.length;

  const clearImaging = () => {
    // Delete from the highest absolute index downward so earlier indices stay
    // valid as the queue shrinks under us.
    const sorted = [...imagingRows].sort((a, b) => b.absoluteIndex - a.absoluteIndex);
    for (const row of sorted) {
      removeQueueItem(row.absoluteIndex);
    }
  };

  return (
    <div
      className="rounded-lg border overflow-hidden flex flex-col shrink-0"
      style={{
        borderColor: sending ? `${colors.info}66` : colors.borderSubtle,
        backgroundColor: colors.bgPanel,
        boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
        height: 280,
      }}
    >
      <div
        className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0"
        style={{ borderColor: colors.borderSubtle }}
      >
        <ListChecks className="size-3.5" style={{ color: colors.dim }} />
        <span
          className="text-[11px] font-bold uppercase tracking-wider"
          style={{ color: colors.value }}
        >
          Imaging Queue
        </span>
        {count > 0 && (
          <span
            className="inline-flex items-center justify-center px-1.5 rounded-sm border text-[11px] font-medium"
            style={{
              height: 20,
              color: sending ? colors.info : colors.active,
              borderColor: `${sending ? colors.info : colors.active}40`,
              backgroundColor: `${sending ? colors.info : colors.active}0A`,
            }}
          >
            {count}
          </span>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-y-auto relative">
        {count === 0 ? (
          <div
            className="absolute inset-0 flex items-center justify-center text-[11px]"
            style={{ color: colors.sep }}
          >
            No staged commands
          </div>
        ) : (
          imagingRows.map((row, idx) => {
            // NEXT / SENDING rails reflect the position in the REAL
            // unfiltered queue — non-imaging commands may be ahead of
            // this row, in which case the row is neither NEXT nor
            // SENDING regardless of its filtered position.
            const isQueueHead = row.absoluteIndex === 0;
            const isNext = isQueueHead && !sending;
            const isSending = sending && isQueueHead;
            const railColor = isSending ? colors.info : isNext ? colors.active : null;
            return (
              <div
                key={row.item.num}
                className="flex items-center gap-2.5 px-3 py-1.5 border-b font-mono text-[11px]"
                style={{
                  borderColor: '#1A1A1A',
                  color: colors.value,
                  boxShadow: railColor ? `inset 2px 0 0 ${railColor}` : 'none',
                  backgroundColor: isSending ? `${colors.info}08` : undefined,
                }}
              >
                <span
                  className="inline-flex items-center justify-center px-1.5 rounded-sm border text-[10px] font-medium"
                  style={{
                    height: 18,
                    color: railColor ?? colors.dim,
                    borderColor: `${railColor ?? colors.dim}40`,
                    backgroundColor: `${railColor ?? colors.dim}0A`,
                  }}
                >
                  {isSending ? 'SENDING' : isNext ? 'NEXT' : `#${idx + 1}`}
                </span>
                <span className="flex-1 truncate">{row.label}</span>
                <span
                  className="text-[10px]"
                  style={{ color: colors.dim }}
                >
                  {row.destLabel}
                </span>
                {!sending && (
                  <button
                    onClick={() => removeQueueItem(row.absoluteIndex)}
                    className="rounded hover:bg-white/[0.04] p-0.5"
                    aria-label={`Remove ${row.cmdId}`}
                  >
                    <X className="size-3" style={{ color: colors.danger }} />
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Footer — Send all / Clear */}
      <div
        className="shrink-0 border-t flex items-center gap-2 px-3 py-2"
        style={{ borderColor: colors.borderSubtle }}
      >
        <span
          className="text-[10px] flex-1"
          style={{ color: sending ? colors.info : colors.dim }}
        >
          {sending
            ? `Sending ${sendProgress!.sent + 1}/${sendProgress!.total}`
            : count === 0
            ? 'No commands staged'
            : `${count} command${count === 1 ? '' : 's'} staged${
                otherCount > 0
                  ? ` · +${otherCount} other command${otherCount === 1 ? '' : 's'} also pending`
                  : ''
              }`}
        </span>
        {count > 0 && !sending && (
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 text-[10px]"
            onClick={clearImaging}
          >
            <X className="size-3" /> Clear
          </Button>
        )}
        {sending ? (
          <Button
            size="sm"
            className="h-6 px-3 text-[10px] font-semibold"
            style={{ backgroundColor: colors.danger, color: colors.bgApp }}
            onClick={abortSend}
          >
            <StopCircle className="size-3" /> Abort
          </Button>
        ) : (
          <Button
            size="sm"
            className="h-6 px-3 text-[10px] font-semibold"
            style={{ backgroundColor: colors.success, color: colors.bgApp }}
            onClick={sendAll}
            disabled={count === 0}
          >
            <Send className="size-3" /> Send all
          </Button>
        )}
      </div>
    </div>
  );
}

/** Short human-readable label for an imaging command in the queue row. */
function describeCmd(
  cmdId: string,
  args: Record<string, string> | undefined,
  item: TxQueueCmd,
): string {
  // Prefer the item's own display title if one exists (matches main TxQueue).
  if (item.display?.title) {
    const subtitle = item.display.subtitle ? ` ${item.display.subtitle}` : '';
    return `${item.display.title}${subtitle}`;
  }
  if (!args) return cmdId;
  const fn = args.Filename ?? args.Filepath ?? '';
  if (cmdId === 'img_get_chunk' && args['Start Chunk'] !== undefined) {
    return `${cmdId} ${fn} start=${args['Start Chunk']} n=${args['Num Chunks']}`;
  }
  if (fn) return `${cmdId} ${fn}`;
  return cmdId;
}
