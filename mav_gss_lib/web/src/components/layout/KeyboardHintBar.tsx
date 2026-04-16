import { useEffect, useState } from 'react'
import { Kbd } from '@/components/ui/kbd'
import { colors } from '@/lib/colors'

type HintContext = 'default' | 'rx-packet' | 'tx-queue' | 'input' | 'plugin'

const hints: Record<HintContext, { key: string; desc: string }[]> = {
  default: [
    { key: 'Ctrl+K', desc: 'Search' },
    { key: 'Ctrl+S', desc: 'Send' },
    { key: 'Ctrl+X', desc: 'Clear' },
    { key: 'Ctrl+Z', desc: 'Undo' },
    { key: '?', desc: 'Help' },
  ],
  'rx-packet': [
    { key: '↑↓', desc: 'Navigate' },
    { key: 'Space', desc: 'Expand' },
    { key: 'Esc', desc: 'Deselect' },
    { key: 'Right-click', desc: 'Copy' },
  ],
  'tx-queue': [
    { key: '↑↓', desc: 'Navigate' },
    { key: 'G', desc: 'Guard' },
    { key: 'Del', desc: 'Remove' },
    { key: 'Drag', desc: 'Reorder' },
  ],
  input: [
    { key: 'Enter', desc: 'Queue' },
    { key: '↑↓', desc: 'History' },
    { key: 'Esc', desc: 'Cancel' },
  ],
  plugin: [
    { key: 'Ctrl+K', desc: 'Search' },
    { key: '?', desc: 'Help' },
  ],
}

interface KeyboardHintBarProps {
  activeTabId: string
  anyShellModalOpen: boolean
}

export function KeyboardHintBar({ activeTabId, anyShellModalOpen }: KeyboardHintBarProps) {
  const [ctx, setCtx] = useState<HintContext>('default')

  useEffect(() => {
    function getContext(): HintContext {
      const el = document.activeElement
      const tag = el?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return 'input'
      if (activeTabId !== '__dashboard__') return 'plugin'
      return 'default'
    }
    function update() { setCtx(getContext()) }

    update()
    document.addEventListener('focusin', update)
    document.addEventListener('focusout', update)
    return () => {
      document.removeEventListener('focusin', update)
      document.removeEventListener('focusout', update)
    }
  }, [activeTabId])

  const baseItems = hints[ctx]
  const items = anyShellModalOpen
    ? [...baseItems, { key: 'Esc', desc: 'Close modal' }]
    : baseItems

  return (
    <div className="flex items-center justify-center gap-4 h-6 px-4 shrink-0 border-t" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgApp }}>
      {items.map((h) => (
        <span key={h.key} className="flex items-center gap-1.5 text-[11px]">
          <Kbd className="!h-4 !min-w-4 !text-[11px] !px-1">{h.key}</Kbd>
          <span style={{ color: colors.dim }}>{h.desc}</span>
        </span>
      ))}
    </div>
  )
}
