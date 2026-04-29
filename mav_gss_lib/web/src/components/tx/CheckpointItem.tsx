import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical, ShieldCheck, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { colors } from '@/lib/colors'
import { col } from '@/lib/columns'
import type { TxRowStatus } from '@/lib/types'

interface CheckpointItemProps {
  text: string
  index: number
  sortId: string
  status: TxRowStatus
  isActive: boolean
  onDelete: (index: number) => void
}

export function CheckpointItem({ text, index, sortId, status, isActive, onDelete }: CheckpointItemProps) {
  const pending = status === 'pending' || status === 'sending'
  const terminal = status === 'complete' || status === 'failed' || status === 'timed_out'

  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id: sortId, disabled: !pending })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : (terminal ? 0.6 : 1),
  }

  return (
    <div
      ref={setNodeRef}
      data-follow-id={sortId}
      style={{ ...style, borderLeftColor: isActive ? colors.warning : colors.active }}
      className={`rounded-md text-xs border-l-2 mb-0.5 ${isActive ? 'animate-pulse-warning' : ''}`}
    >
      <div className="flex items-center gap-1.5 px-1.5 py-0.5">
        {pending ? (
          <span {...attributes} {...listeners}
            className={`${col.grip} cursor-grab shrink-0 p-0.5 rounded hover:bg-white/[0.06] flex items-center justify-center`}>
            <GripVertical className="size-3.5" style={{ color: colors.dim }} />
          </span>
        ) : (
          <span className={`${col.grip} shrink-0`} aria-hidden="true" />
        )}
        <ShieldCheck className="size-3.5 shrink-0" style={{ color: isActive ? colors.warning : colors.active }} />
        <span className="shrink-0 font-semibold" style={{ color: isActive ? colors.warning : colors.active }}>
          checkpoint
        </span>
        <span className="flex-1 min-w-0 truncate" style={{ color: colors.value }}>{text}</span>
        {pending ? (
          <Button variant="ghost" size="icon" className="size-5 rounded shrink-0"
            onClick={() => onDelete(index)} title="Remove checkpoint">
            <Trash2 className="size-3" style={{ color: colors.dim }} />
          </Button>
        ) : (
          <span className="size-5 shrink-0" aria-hidden="true" />
        )}
      </div>
    </div>
  )
}
