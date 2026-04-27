import * as CM from '@radix-ui/react-context-menu'
import { colors } from '@/lib/colors'
import type { ReactNode } from 'react'

export function ContextMenuRoot({ children }: { children: ReactNode }) {
  return <CM.Root>{children}</CM.Root>
}

export function ContextMenuTrigger({ children }: { children: ReactNode }) {
  return <CM.Trigger asChild>{children}</CM.Trigger>
}

export function ContextMenuContent({ children }: { children: ReactNode }) {
  return (
    <CM.Portal>
      <CM.Content
        className="z-50 min-w-[160px] rounded-md p-1 shadow-overlay"
        style={{ backgroundColor: colors.bgPanelRaised, border: `1px solid ${colors.borderSubtle}` }}
      >
        {children}
      </CM.Content>
    </CM.Portal>
  )
}

export function ContextMenuItem({
  children, icon: Icon, onSelect, destructive,
}: {
  children: ReactNode
  icon?: React.ElementType
  onSelect: () => void
  destructive?: boolean
}) {
  return (
    <CM.Item
      className="flex items-center gap-2 px-2 py-1.5 text-xs font-medium rounded-sm cursor-pointer outline-none data-[highlighted]:bg-white/[0.08]"
      style={{ color: destructive ? colors.error : colors.value }}
      onSelect={onSelect}
    >
      {Icon && <Icon className="size-3.5" style={{ color: destructive ? colors.error : colors.dim }} />}
      {children}
    </CM.Item>
  )
}

export function ContextMenuSeparator() {
  return <CM.Separator className="my-1 h-px" style={{ backgroundColor: colors.borderSubtle }} />
}
