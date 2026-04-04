import { colors } from '@/lib/colors'
import { X } from 'lucide-react'

interface HelpModalProps {
  open: boolean
  onClose: () => void
}

interface ShortcutRow {
  keys: string
  desc: string
}

const sections: { title: string; items: ShortcutRow[] }[] = [
  {
    title: 'SENDING',
    items: [
      { keys: 'Ctrl+S', desc: 'Send all queued commands' },
      { keys: 'Ctrl+C / Esc', desc: 'Abort current send' },
    ],
  },
  {
    title: 'QUEUE MANAGEMENT',
    items: [
      { keys: 'Drag', desc: 'Reorder queue items' },
      { keys: 'Click row', desc: 'Select / deselect item' },
      { keys: 'Guard toggle', desc: 'Mark item for confirmation' },
      { keys: 'Delete', desc: 'Remove selected item' },
      { keys: 'Ctrl+Z', desc: 'Undo last queue action' },
    ],
  },
  {
    title: 'COMMAND INPUT',
    items: [
      { keys: 'CMD [ARGS]', desc: 'Shorthand entry (when schema has routing defaults)' },
      { keys: '[SRC] DEST ECHO TYPE CMD [ARGS]', desc: 'Full command form' },
      { keys: 'Up / Down', desc: 'Browse command history' },
      { keys: 'Enter', desc: 'Queue the command' },
    ],
  },
  {
    title: 'RX MONITORING',
    items: [
      { keys: 'Click row', desc: 'View packet details' },
      { keys: 'HEX pill', desc: 'Toggle hex display' },
      { keys: 'UL pill', desc: 'Toggle uplink echo visibility' },
      { keys: 'FRAME pill', desc: 'Toggle frame type column' },
      { keys: 'LIVE button', desc: 'Toggle auto-scroll to latest' },
    ],
  },
]

export function HelpModal({ open, onClose }: HelpModalProps) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
         style={{ backgroundColor: 'rgba(0,0,0,0.7)' }}
         onClick={onClose}>
      <div className="w-[640px] max-h-[80vh] overflow-y-auto rounded-lg border border-[#333] p-5"
           style={{ backgroundColor: colors.bgPanel }}
           onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <span className="text-sm font-bold" style={{ color: colors.label }}>
            Keyboard Shortcuts & Controls
          </span>
          <button onClick={onClose} className="p-1 rounded hover:bg-white/5">
            <X className="size-4" style={{ color: colors.dim }} />
          </button>
        </div>

        {/* 2-column grid */}
        <div className="grid grid-cols-2 gap-4">
          {sections.map((section) => (
            <div key={section.title}>
              <div className="text-xs font-bold uppercase tracking-wider mb-2"
                   style={{ color: colors.label }}>
                {section.title}
              </div>
              <div className="flex flex-col gap-1.5">
                {section.items.map((item) => (
                  <div key={item.keys} className="flex items-start gap-2">
                    <span className="text-xs font-mono shrink-0 px-1.5 py-0.5 rounded"
                          style={{ backgroundColor: `${colors.label}15`, color: colors.value }}>
                      {item.keys}
                    </span>
                    <span className="text-xs pt-0.5" style={{ color: colors.dim }}>
                      {item.desc}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Footer hint */}
        <div className="mt-4 pt-3 border-t border-[#333] text-xs text-center" style={{ color: colors.dim }}>
          Press <span style={{ color: colors.value }}>?</span> or <span style={{ color: colors.value }}>Esc</span> to close
        </div>
      </div>
    </div>
  )
}
