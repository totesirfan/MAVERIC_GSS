import { useEffect } from 'react'
import { colors } from '@/lib/colors'

interface ConfirmBarProps {
  label: string
  /** Accent color for border, text, and Confirm button fill */
  color: string
  onConfirm: () => void
  onCancel: () => void
  confirmLabel?: string
  cancelLabel?: string
  /**
   * If true (default), the keybind listener runs in the window capture phase
   * and calls stopImmediatePropagation on Enter/Escape so outer listeners
   * (e.g. App's "return to dashboard on Escape" shortcut) can't steal the key.
   */
  captureKeys?: boolean
}

/**
 * Pulsing bottom-bar that pins to the edge of a card with `border-t` and asks
 * the operator to Confirm / Cancel an action. Shared by TxQueue and the
 * imaging page so every confirm looks and behaves identically.
 */
export function ConfirmBar({
  label,
  color,
  onConfirm,
  onCancel,
  confirmLabel = 'Confirm ↵',
  cancelLabel = 'Esc',
  captureKeys = true,
}: ConfirmBarProps) {
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        if (captureKeys) e.stopImmediatePropagation()
        onConfirm()
      } else if (e.key === 'Escape') {
        e.preventDefault()
        if (captureKeys) e.stopImmediatePropagation()
        onCancel()
      }
    }
    window.addEventListener('keydown', handleKey, { capture: captureKeys })
    return () => window.removeEventListener('keydown', handleKey, { capture: captureKeys })
  }, [onConfirm, onCancel, captureKeys])

  return (
    <div
      className="flex items-center justify-between px-3 py-1.5 border-t shrink-0 animate-pulse-action"
      style={{ borderColor: color, backgroundColor: `${color}18` }}
    >
      <span className="text-xs font-bold truncate mr-2" style={{ color }}>{label}</span>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={onCancel}
          className="text-[11px] px-2 py-0.5 rounded border btn-feedback"
          style={{ color: colors.dim, borderColor: colors.borderSubtle }}
        >
          {cancelLabel}
        </button>
        <button
          onClick={onConfirm}
          className="text-[11px] px-3 py-0.5 rounded font-bold btn-feedback"
          style={{ backgroundColor: color, color: colors.bgApp }}
        >
          {confirmLabel}
        </button>
      </div>
    </div>
  )
}
