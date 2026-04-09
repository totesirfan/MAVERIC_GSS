import { useEffect, useRef } from 'react'
import { useShortcuts } from '@/hooks/useShortcuts'
import { motion, AnimatePresence } from 'framer-motion'
import { colors } from '@/lib/colors'
import {
  Command, CommandInput, CommandList, CommandEmpty,
  CommandGroup, CommandItem, CommandShortcut,
} from '@/components/ui/command'
import {
  Send, Trash2, Undo, Binary, Radio, Shield,
  Settings, FileText, HelpCircle, Eye, Plus, Tag,
} from 'lucide-react'

interface CommandPaletteProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  actions: {
    confirmSend: () => void
    confirmClear: () => void
    undoLast: () => void
    abortSend: () => void
    toggleHex: () => void
    toggleUplink: () => void
    toggleFrame: () => void
    toggleWrapper: () => void
    openConfig: () => void
    openLogs: () => void
    openHelp: () => void
    newSession: () => void
    tagSession: () => void
  }
}

const springConfig = { type: 'spring' as const, stiffness: 500, damping: 30, mass: 0.8 }
let hasLoadedCommandPalette = false

export function CommandPalette({ open, onOpenChange, actions }: CommandPaletteProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const animateOnMount = hasLoadedCommandPalette

  useEffect(() => {
    hasLoadedCommandPalette = true
  }, [])

  function run(fn: () => void) {
    fn()
    onOpenChange(false)
  }

  // Focus input when opened
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50)
  }, [open])

  // Escape closes
  useShortcuts(
    [{ key: 'Escape', action: () => onOpenChange(false) }],
    open,
  )

  return (
    <AnimatePresence initial={false}>
      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]" onClick={() => onOpenChange(false)}>
          <motion.div
            className="absolute inset-0 frosted-backdrop"
            style={{ backgroundColor: 'rgba(0,0,0,0.7)' }}
            initial={animateOnMount ? { opacity: 0 } : false}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
          />
          <motion.div
            className="relative z-10 w-[480px] shadow-overlay rounded-xl overflow-hidden border"
            style={{ backgroundColor: colors.bgPanelRaised, borderColor: colors.borderStrong }}
            onClick={(e) => e.stopPropagation()}
            initial={animateOnMount ? { opacity: 0, scale: 0.95, y: -10 } : false}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -10 }}
            transition={springConfig}
          >
            <Command className="bg-transparent">
              <CommandInput ref={inputRef} placeholder="Search..." />
              <CommandList>
                <CommandEmpty>No results found.</CommandEmpty>

                <CommandGroup heading="Uplink">
                  <CommandItem onSelect={() => run(actions.confirmSend)}>
                    <Send className="size-4" />
                    <span>Send All...</span>
                    <CommandShortcut>Ctrl+S</CommandShortcut>
                  </CommandItem>
                  <CommandItem onSelect={() => run(actions.confirmClear)}>
                    <Trash2 className="size-4" />
                    <span>Clear Queue...</span>
                    <CommandShortcut>Ctrl+X</CommandShortcut>
                  </CommandItem>
                  <CommandItem onSelect={() => run(actions.undoLast)}>
                    <Undo className="size-4" />
                    <span>Undo Last</span>
                    <CommandShortcut>Ctrl+Z</CommandShortcut>
                  </CommandItem>
                  <CommandItem onSelect={() => run(actions.abortSend)}>
                    <Shield className="size-4" />
                    <span>Abort Send</span>
                    <CommandShortcut>Esc</CommandShortcut>
                  </CommandItem>
                </CommandGroup>

                <CommandGroup heading="Downlink Display">
                  <CommandItem onSelect={() => run(actions.toggleHex)}>
                    <Binary className="size-4" />
                    <span>Toggle Hex Display</span>
                  </CommandItem>
                  <CommandItem onSelect={() => run(actions.toggleUplink)}>
                    <Eye className="size-4" />
                    <span>Toggle Uplink Echoes</span>
                  </CommandItem>
                  <CommandItem onSelect={() => run(actions.toggleFrame)}>
                    <Radio className="size-4" />
                    <span>Toggle Frame Column</span>
                  </CommandItem>
                  <CommandItem onSelect={() => run(actions.toggleWrapper)}>
                    <Shield className="size-4" />
                    <span>Toggle CRC/CSP/AX.25</span>
                  </CommandItem>
                </CommandGroup>

                <CommandGroup heading="Logging">
                  <CommandItem onSelect={() => run(actions.newSession)}>
                    <Plus className="size-4" />
                    <span>New Log Session</span>
                  </CommandItem>
                  <CommandItem onSelect={() => run(actions.tagSession)}>
                    <Tag className="size-4" />
                    <span>Tag Current Session</span>
                  </CommandItem>
                </CommandGroup>

                <CommandGroup heading="Panels">
                  <CommandItem onSelect={() => run(actions.openConfig)}>
                    <Settings className="size-4" />
                    <span>Open Configuration</span>
                  </CommandItem>
                  <CommandItem onSelect={() => run(actions.openLogs)}>
                    <FileText className="size-4" />
                    <span>Open Log Viewer</span>
                  </CommandItem>
                  <CommandItem onSelect={() => run(actions.openHelp)}>
                    <HelpCircle className="size-4" />
                    <span>Help & Shortcuts</span>
                    <CommandShortcut>?</CommandShortcut>
                  </CommandItem>
                </CommandGroup>
              </CommandList>
            </Command>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
