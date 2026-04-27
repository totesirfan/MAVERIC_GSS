import { useEffect, useCallback, useRef } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { colors } from '@/lib/colors'

interface ConfirmDialogProps {
  open: boolean
  title: string
  detail?: string
  content?: React.ReactNode
  variant?: 'normal' | 'caution' | 'destructive'
  onConfirm: () => void
  onCancel: () => void
}

const borderColors: Record<string, string> = {
  normal: colors.label,
  caution: colors.warning,
  destructive: colors.error,
}

const springConfig = { type: 'spring' as const, stiffness: 500, damping: 30, mass: 0.8 }

export function ConfirmDialog({
  open, title, detail, content, variant = 'normal',
  onConfirm, onCancel,
}: ConfirmDialogProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<Element | null>(null)

  // Capture trigger element on open, restore on close
  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement
    } else if (triggerRef.current && triggerRef.current instanceof HTMLElement) {
      triggerRef.current.focus()
      triggerRef.current = null
    }
  }, [open])

  // Focus trap
  const handleTab = useCallback((e: KeyboardEvent) => {
    if (e.key !== 'Tab' || !panelRef.current) return
    const focusable = panelRef.current.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey) {
      if (document.activeElement === first) { e.preventDefault(); last.focus() }
    } else {
      if (document.activeElement === last) { e.preventDefault(); first.focus() }
    }
  }, [])

  const handleKey = useCallback((e: KeyboardEvent) => {
    if (!open) return
    if (e.key === 'Enter') { e.preventDefault(); onConfirm() }
    if (e.key === 'Escape') { e.preventDefault(); onCancel() }
    handleTab(e)
  }, [open, onConfirm, onCancel, handleTab])

  useEffect(() => {
    if (!open) return
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, handleKey])

  // Auto-focus panel on open
  useEffect(() => {
    if (open && panelRef.current) {
      const first = panelRef.current.querySelector<HTMLElement>('button')
      first?.focus()
    }
  }, [open])

  const borderColor = borderColors[variant]
  const btnColor = borderColors[variant]

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ backgroundColor: colors.modalBackdrop }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onClick={onCancel}
        >
          <motion.div
            ref={panelRef}
            className="relative z-10 rounded-lg p-4 min-w-[300px] max-w-[400px] border shadow-overlay"
            style={{ backgroundColor: colors.bgPanelRaised, borderColor }}
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.95, opacity: 0 }}
            transition={springConfig}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-sm font-bold mb-2" style={{ color: colors.value }}>{title}</div>
            {detail && <div className="text-xs mb-3" style={{ color: colors.dim }}>{detail}</div>}
            {content && <div className="mb-3">{content}</div>}
            <div className="flex justify-end gap-2">
              <button onClick={onCancel} className="px-3 py-1 rounded text-xs border" style={{ color: colors.dim, borderColor: colors.borderSubtle }}>
                Cancel
              </button>
              <button onClick={onConfirm} className="px-3 py-1 rounded text-xs font-medium btn-feedback"
                style={{ color: colors.bgBase, backgroundColor: btnColor }}>
                Confirm ↵
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
