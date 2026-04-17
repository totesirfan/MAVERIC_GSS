import type { ReactNode } from 'react'

interface CardProps {
  title: string
  /** Optional right-aligned status chip (e.g., current mode). */
  status?: ReactNode
  children: ReactNode
}

export function Card({ title, status, children }: CardProps) {
  return (
    <div className="flex flex-col bg-black border border-[#222222] rounded-sm">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#1a1a1a]">
        <h3 className="font-sans text-[12px] uppercase tracking-wider text-[#E5E5E5]">
          {title}
        </h3>
        {status}
      </div>
      <div className="flex-1">
        {children}
      </div>
    </div>
  )
}
