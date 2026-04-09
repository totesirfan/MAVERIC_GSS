import { useState, type InputHTMLAttributes, type Ref } from 'react'
import { cn } from '@/lib/utils'
import { colors } from '@/lib/colors'

export function GssInput({ className, style, onFocus, onBlur, ref, ...props }: InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  const [focused, setFocused] = useState(false)
  return (
    <input
      {...props}
      ref={ref}
      onFocus={(e) => { setFocused(true); onFocus?.(e) }}
      onBlur={(e) => { setFocused(false); onBlur?.(e) }}
      className={cn('px-2 py-1 rounded text-xs outline-none border focus:ring-1', className)}
      style={{
        backgroundColor: colors.bgBase,
        color: colors.value,
        borderColor: focused ? colors.active : colors.borderSubtle,
        '--tw-ring-color': `${colors.active}33`,
        ...style,
      } as React.CSSProperties}
    />
  )
}
