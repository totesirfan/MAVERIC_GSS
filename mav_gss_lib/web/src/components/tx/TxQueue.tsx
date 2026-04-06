import { useState, useEffect, useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  DndContext, closestCenter,
  PointerSensor, useSensor, useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy, arrayMove } from '@dnd-kit/sortable'
import { Trash2, Send, Timer, Save } from 'lucide-react'
import { PromptDialog } from '@/components/shared/PromptDialog'
import { PanelToasts } from '@/components/shared/StatusToast'
import { showToast } from '@/components/shared/StatusToast'
import { authFetch } from '@/lib/auth'
import {
  ContextMenuRoot, ContextMenuTrigger, ContextMenuContent,
  ContextMenuItem,
} from '@/components/shared/ContextMenu'
import { Button } from '@/components/ui/button'
import { QueueItem } from './QueueItem'
import { DelayItem } from './DelayItem'
import { colors } from '@/lib/colors'
import { col } from '@/lib/columns'
import type { GssConfig, TxQueueItem, TxQueueSummary, SendProgress } from '@/lib/types'

interface TxQueueProps {
  nodeDescriptions?: GssConfig['node_descriptions']
  queue: TxQueueItem[]
  summary: TxQueueSummary
  sendProgress: SendProgress | null
  isGuarding: boolean
  onToggleGuard: (index: number) => void
  onDelete: (index: number) => void
  onEditDelay: (index: number, ms: number) => void
  onReorder: (oldIndex: number, newIndex: number) => void
  onAddDelay: (ms: number) => void
  onClear: () => void
  onSend: () => void
  onDuplicate: (index: number) => void
  onMoveToTop: (index: number) => void
  onMoveToBottom: (index: number) => void
  triggerConfirmSend?: number
  triggerConfirmClear?: number
}

// Assign stable unique IDs to items so dnd-kit can track them across reorders
let nextUid = 1
function assignUids(items: TxQueueItem[]): { item: TxQueueItem; uid: number }[] {
  return items.map(item => ({ item, uid: nextUid++ }))
}

export function TxQueue({
  nodeDescriptions, queue, summary, sendProgress, isGuarding,
  onToggleGuard, onDelete, onEditDelay, onReorder, onAddDelay,
  onClear, onSend, onDuplicate, onMoveToTop, onMoveToBottom,
  triggerConfirmSend, triggerConfirmClear,
}: TxQueueProps) {
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null)
  const [focusedIdx, setFocusedIdx] = useState<number | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const [confirmSend, setConfirmSend] = useState(false)
  const [showSavePrompt, setShowSavePrompt] = useState(false)

  // External triggers (from command palette)
  useEffect(() => { if (triggerConfirmSend) setConfirmSend(true) }, [triggerConfirmSend])
  useEffect(() => { if (triggerConfirmClear) setConfirmClear(true) }, [triggerConfirmClear])
  const [uidItems, setUidItems] = useState(() => assignUids(queue))
  const [flashUid, setFlashUid] = useState<number | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const ignoreNextSync = useRef(false)
  const prevLenRef = useRef(queue.length)

  // Sync from backend — preserve uids for existing items
  useEffect(() => {
    if (ignoreNextSync.current) {
      ignoreNextSync.current = false
      prevLenRef.current = queue.length
      return
    }
    setUidItems(prev => {
      const prevLen = prev.length
      const newLen = queue.length
      if (newLen === 0) return []
      // Items removed from front (send) — keep uids for remaining items
      if (newLen < prevLen) {
        const removed = prevLen - newLen
        return prev.slice(removed).map((entry, i) => ({ item: queue[i], uid: entry.uid }))
      }
      // Items added at end — keep existing uids, assign new for additions
      const kept = prev.map((entry, i) => ({ item: queue[i], uid: entry.uid }))
      const added = queue.slice(prevLen).map(item => ({ item, uid: nextUid++ }))
      const result = [...kept, ...added]
      // Flash newest
      if (added.length > 0) {
        const newestUid = added[added.length - 1].uid
        setFlashUid(newestUid)
        setTimeout(() => setFlashUid(null), 300)
      }
      return result
    })
    const grew = queue.length > prevLenRef.current
    prevLenRef.current = queue.length
    if (grew) {
      requestAnimationFrame(() => {
        if (scrollRef.current) scrollRef.current.scrollTop = 0
      })
    }
  }, [queue])


  // Keyboard navigation within the queue area
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      const tag = document.activeElement?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (uidItems.length === 0) return

      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault()
        setFocusedIdx(prev => {
          const max = uidItems.length - 1
          if (prev === null) return 0
          if (e.key === 'ArrowUp') return Math.max(0, prev - 1)
          return Math.min(max, prev + 1)
        })
        return
      }
      if ((e.key === 'Delete' || e.key === 'Backspace') && focusedIdx !== null) {
        e.preventDefault()
        onDelete(focusedIdx)
        return
      }
      if ((e.key === 'g' || e.key === 'G') && focusedIdx !== null && !e.ctrlKey && !e.metaKey) {
        e.preventDefault()
        onToggleGuard(focusedIdx)
        return
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [uidItems.length, focusedIdx, onDelete, onToggleGuard])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  )

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIdx = uidItems.findIndex(u => `uid-${u.uid}` === active.id)
    const newIdx = uidItems.findIndex(u => `uid-${u.uid}` === over.id)
    if (oldIdx === -1 || newIdx === -1) return

    // Optimistic: reorder locally with stable UIDs — card stays where dropped
    setUidItems(prev => arrayMove(prev, oldIdx, newIdx))
    ignoreNextSync.current = true
    onReorder(oldIdx, newIdx)
    setSelectedIdx(null)
  }

  const estStr = summary.est_time_s > 0 ? `~${summary.est_time_s.toFixed(1)}s` : ''

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Column headers — fixed above scroll */}
      {uidItems.length > 0 && (
        <div className="flex items-center gap-1.5 px-3.5 py-0.5 text-xs font-light shrink-0" style={{ color: colors.dim }}>
          <span className={col.grip} />
          <span className={`${col.num} text-right`}>#</span>
          <span className={col.node}>dest</span>
          <span className={col.ptype}>type</span>
          <span className="flex-1">cmd / args</span>
          <span className={`${col.size} text-right`}>size</span>
          <span className={col.actions} />
        </div>
      )}
      <ContextMenuRoot>
      <ContextMenuTrigger>
      <div ref={scrollRef} className="flex-1 overflow-y-auto overflow-x-hidden px-2 py-1 flex flex-col">
        {uidItems.length === 0 ? (
          <div className="flex items-center justify-center h-full text-xs" style={{ color: colors.dim }}>
            Queue empty — type a command below
          </div>
        ) : (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <SortableContext items={[...uidItems].reverse().map(u => `uid-${u.uid}`)} strategy={verticalListSortingStrategy}>
              <div className="mt-auto" />
              <AnimatePresence initial={false}>
              {[...uidItems].reverse().map(({ item, uid }) => {
                const realIdx = uidItems.findIndex(u => u.uid === uid)
                const isFlashing = flashUid === uid
                if (item.type === 'delay') {
                  const delayActive = sendProgress !== null && sendProgress.waiting === true && realIdx === 0
                  return (
                    <motion.div key={uid} exit={{ opacity: 0, x: 30 }} transition={{ duration: 0.15 }} className={isFlashing ? 'animate-slide-in' : ''}>
                      <DelayItem delayMs={item.delay_ms} index={realIdx} sortId={`uid-${uid}`} isActive={delayActive} onEditDelay={onEditDelay} onDelete={onDelete} />
                    </motion.div>
                  )
                }
                // Index 0 = next to send (now at bottom visually)
                const isSending = sendProgress !== null && realIdx === 0
                const isNext = !sendProgress && realIdx === 0
                const itemGuarding = isGuarding && realIdx === 0
                return (
                  <motion.div key={uid} exit={{ opacity: 0, x: 30 }} transition={{ duration: 0.15 }}>
                    <QueueItem
                      item={{ ...item, num: realIdx + 1 }}
                      nodeDescriptions={nodeDescriptions}
                      index={realIdx}
                      sortId={`uid-${uid}`}
                      expanded={selectedIdx === realIdx}
                      isNext={isNext}
                      isSending={isSending}
                      isGuarding={itemGuarding}
                      flash={isFlashing}
                      onSelect={() => setSelectedIdx(selectedIdx === realIdx ? null : realIdx)}
                      onToggleGuard={onToggleGuard}
                      onDelete={onDelete}
                      onDuplicate={onDuplicate}
                      onMoveToTop={onMoveToTop}
                      onMoveToBottom={onMoveToBottom}
                    />
                  </motion.div>
                )
              })}
              </AnimatePresence>
            </SortableContext>
          </DndContext>
        )}
      </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem icon={Save} onSelect={() => setShowSavePrompt(true)}>
          Save Queue
        </ContextMenuItem>
      </ContextMenuContent>
      </ContextMenuRoot>

      <PanelToasts side="tx" />

      {/* Bottom bar: normal or full-bar confirm */}
      {confirmClear ? (
        <ConfirmBar
          label="Clear all commands?"
          color={colors.error}
          onConfirm={() => { onClear(); setConfirmClear(false) }}
          onCancel={() => setConfirmClear(false)}
        />
      ) : confirmSend ? (
        <ConfirmBar
          label={`Send ${summary.cmds} command${summary.cmds !== 1 ? 's' : ''}?`}
          color={colors.success}
          onConfirm={() => { onSend(); setConfirmSend(false) }}
          onCancel={() => setConfirmSend(false)}
        />
      ) : (
        <div className="flex items-center justify-between px-3 py-1 border-t shrink-0" style={{ borderColor: colors.borderSubtle }}>
          <span className="text-[11px]" style={{ color: colors.dim }}>
            {summary.cmds} cmd{summary.cmds !== 1 ? 's' : ''}
            {summary.guards > 0 ? ` · ${summary.guards} guarded` : ''}
            {estStr ? ` · ${estStr}` : ''}
          </span>
          <div className="flex items-center gap-1.5">
            <Button variant="ghost" size="sm" onClick={() => onAddDelay(2000)} className="h-6 px-2 text-xs gap-1" style={{ color: colors.dim }}>
              <Timer className="size-3" /> Delay
            </Button>
            <Button variant="ghost" size="sm" onClick={() => { setConfirmClear(true); setConfirmSend(false) }}
              className="h-6 px-2 text-xs gap-1 hover:!text-[#F06060]" style={{ color: colors.dim }}>
              <Trash2 className="size-3" /> Clear
            </Button>
            <Button size="sm" onClick={() => { setConfirmSend(true); setConfirmClear(false) }}
              className="h-6 px-2 text-xs gap-1 btn-feedback"
              style={{ color: colors.bgBase, backgroundColor: colors.success }}>
              <Send className="size-3" /> Send All
            </Button>
          </div>
        </div>
      )}
        <PromptDialog
          open={showSavePrompt}
          title="Save Queue"
          placeholder="File name (optional)"
          onSubmit={(name) => {
            setShowSavePrompt(false)
            authFetch('/api/export-queue', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name }),
            }).then(r => r.json()).then(d => {
            if (d.ok) showToast(`Saved ${d.count} commands as ${d.filename}`, 'success')
            else showToast(d.error || 'Save failed', 'error')
          }).catch(() => showToast('Failed to save queue', 'error'))
        }}
        onCancel={() => setShowSavePrompt(false)}
      />
    </div>
  )
}

function ConfirmBar({ label, color, onConfirm, onCancel }: {
  label: string; color: string; onConfirm: () => void; onCancel: () => void
}) {
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Enter') { e.preventDefault(); onConfirm() }
      if (e.key === 'Escape') { e.preventDefault(); onCancel() }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onConfirm, onCancel])

  return (
    <div
      className="flex items-center justify-between px-3 py-1.5 border-t shrink-0 animate-pulse-action"
      style={{ borderColor: color, backgroundColor: `${color}18` }}
    >
      <span className="text-xs font-bold" style={{ color }}>{label}</span>
      <div className="flex items-center gap-2">
        <button onClick={onCancel} className="text-[11px] px-2 py-0.5 rounded border btn-feedback"
          style={{ color: colors.dim, borderColor: colors.borderSubtle }}>
          Esc
        </button>
        <button onClick={onConfirm} className="text-[11px] px-3 py-0.5 rounded font-bold btn-feedback"
          style={{ backgroundColor: color, color: colors.bgApp }}>
          Confirm ↵
        </button>
      </div>
    </div>
  )
}
