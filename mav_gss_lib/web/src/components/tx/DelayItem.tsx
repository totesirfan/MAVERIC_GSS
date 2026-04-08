import { useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Timer, GripVertical, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover'
import { colors } from '@/lib/colors'

interface DelayItemProps {
  delayMs: number
  index: number
  sortId: string
  isActive: boolean
  onEditDelay: (index: number, ms: number) => void
  onDelete: (index: number) => void
}

export function DelayItem({ delayMs, index, sortId, isActive, onEditDelay, onDelete }: DelayItemProps) {
  const [open, setOpen] = useState(false)
  const [remaining, setRemaining] = useState(delayMs)
  const startTime = useRef<number | null>(null)

  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id: sortId })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!isActive) { startTime.current = null; setRemaining(delayMs); return }
    startTime.current = Date.now()
    const id = setInterval(() => {
      setRemaining(Math.max(0, delayMs - (Date.now() - (startTime.current ?? Date.now()))))
    }, 50)
    return () => clearInterval(id)
  }, [isActive, delayMs])
  /* eslint-enable react-hooks/set-state-in-effect */

  return (
    <div
      ref={setNodeRef}
      style={{ ...style, borderLeftColor: colors.label }}
      className="rounded-md text-xs border-l-2 mb-0.5 relative overflow-hidden"
    >
      {isActive && (
        <motion.div
          className="absolute inset-y-0 left-0 z-0"
          style={{ backgroundColor: `${colors.warning}20` }}
          initial={{ width: '100%' }}
          animate={{ width: `${(remaining / delayMs) * 100}%` }}
          transition={{ duration: 0.05, ease: 'linear' }}
        />
      )}

      <div className="flex items-center gap-1.5 px-1.5 py-1.5 relative z-10">
        {/* Drag handle */}
        <span {...attributes} {...listeners} className="cursor-grab shrink-0 p-0.5 rounded hover:bg-white/[0.06]">
          <GripVertical className="size-3.5" style={{ color: colors.dim }} />
        </span>

        <Timer className="size-3.5 shrink-0 color-transition" style={{ color: isActive ? colors.warning : colors.dim }} />

        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger
            disabled={isActive}
            className="font-semibold cursor-pointer color-transition"
            style={{ color: isActive ? colors.warning : colors.dim }}
          >
            {isActive ? `${(remaining / 1000).toFixed(1)}s` : `${(delayMs / 1000).toFixed(1)}s`}
          </PopoverTrigger>
          <PopoverContent side="top" className="w-40 p-2">
            <div className="flex items-center gap-1">
              <input
                autoFocus
                type="number"
                className="flex-1 bg-transparent border rounded px-2 py-1 text-xs text-center outline-none"
                style={{ borderColor: colors.label, color: colors.value }}
                defaultValue={String(delayMs)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    const ms = parseInt((e.target as HTMLInputElement).value, 10)
                    if (!isNaN(ms) && ms > 0) onEditDelay(index, ms)
                    setOpen(false)
                  }
                }}
              />
              <span className="text-[11px]" style={{ color: colors.dim }}>ms</span>
            </div>
          </PopoverContent>
        </Popover>

        <span style={{ color: colors.dim }}>delay</span>

        <div className="flex-1" />

        {!isActive && (
          <Button variant="ghost" size="icon" className="size-5 rounded shrink-0"
            onClick={() => onDelete(index)} title="Remove delay">
            <Trash2 className="size-3" style={{ color: colors.dim }} />
          </Button>
        )}
      </div>
    </div>
  )
}
