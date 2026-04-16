import { useReducedMotion, motion } from 'framer-motion'
import { colors } from '@/lib/colors'
import type { NavigationTabDef } from '@/components/layout/navigation'

interface TabStripProps {
  tabs: NavigationTabDef[]
  activeId: string
  onTabClick: (id: string) => void
}

export function TabStrip({ tabs, activeId, onTabClick }: TabStripProps) {
  const reducedMotion = useReducedMotion()
  let prevCategory: string | null = null

  return (
    <div className="flex items-stretch relative" style={{ height: 36 }}>
      {tabs.map((t) => {
        const isActive = activeId === t.id
        const isDashboard = t.kind === 'dashboard'
        const needsDivider = prevCategory !== null && prevCategory !== t.category
        prevCategory = t.category

        const activeColor = isDashboard ? colors.value : colors.active
        const tabColor = isActive ? activeColor : colors.dim

        return (
          <div key={t.id} className="flex items-stretch">
            {needsDivider && (
              <div
                className="self-center"
                style={{
                  width: 1,
                  height: 16,
                  background: colors.borderStrong,
                  margin: '0 6px',
                }}
              />
            )}
            <button
              onClick={() => onTabClick(t.id)}
              className="flex items-center gap-[7px] relative cursor-default"
              style={{
                color: tabColor,
                fontSize: 11,
                fontWeight: 500,
                letterSpacing: '0.2px',
                height: 36,
                background: 'transparent',
                border: 'none',
                padding: '0 14px',
              }}
              onMouseEnter={(e) => {
                if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.04)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent'
              }}
            >
              <t.icon
                style={{ width: 14, height: 14, strokeWidth: 1.8 }}
              />
              <span>{t.name}</span>
              {isActive && (
                <motion.div
                  layoutId="active-tab-underline"
                  className="absolute bottom-0"
                  style={{
                    left: 4,
                    right: 4,
                    height: 2,
                    background: colors.active,
                    borderRadius: 1,
                  }}
                  transition={
                    reducedMotion
                      ? { duration: 0 }
                      : { duration: 0.22, ease: [0.4, 0, 0.2, 1] }
                  }
                />
              )}
            </button>
          </div>
        )
      })}
    </div>
  )
}
