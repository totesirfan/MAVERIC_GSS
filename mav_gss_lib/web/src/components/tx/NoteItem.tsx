import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical, Trash2, MessageSquareText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { colors } from '@/lib/colors'

interface NoteItemProps {
  text: string
  index: number
  sortId: string
  flash?: boolean
  onDelete: (index: number) => void
}

export function NoteItem({ text, index, sortId, flash, onDelete }: NoteItemProps) {
  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id: sortId })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <div
      ref={setNodeRef}
      style={{ ...style, borderLeftColor: colors.dim }}
      className={`rounded-md text-xs border-l-2 mb-0.5 ${flash ? 'animate-slide-in' : ''}`}
    >
      <div className="flex items-center gap-1.5 px-1.5 py-1.5">
        <span {...attributes} {...listeners} className="cursor-grab shrink-0 p-0.5 rounded hover:bg-white/[0.06]">
          <GripVertical className="size-3.5" style={{ color: colors.dim }} />
        </span>
        <MessageSquareText className="size-3.5 shrink-0" style={{ color: colors.dim }} />
        <span className="flex-1 min-w-0 truncate italic" style={{ color: colors.dim }}>{text}</span>
        <Button variant="ghost" size="icon" className="size-5 rounded shrink-0"
          onClick={() => onDelete(index)} title="Remove note">
          <Trash2 className="size-3" style={{ color: colors.dim }} />
        </Button>
      </div>
    </div>
  )
}
