import { useReducedMotion, motion } from 'framer-motion'
import { colors } from '@/lib/colors'
import type { NavigationTabDef } from '@/lib/navigation'

interface TabStripProps {
  tabs: NavigationTabDef[]
  activeId: string
  onTabClick: (id: string) => void
}

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.03 } },
}

const tabVariants = {
  hidden: { opacity: 0, x: -8 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.2, ease: [0.4, 0, 0.2, 1] as const } },
}

export function TabStrip({ tabs, activeId, onTabClick }: TabStripProps) {
  const reducedMotion = useReducedMotion()
  let prevCategory: string | null = null

  return (
    <motion.div
      className="flex items-stretch relative"
      style={{ height: 30 }}
      variants={reducedMotion ? undefined : containerVariants}
      initial="hidden"
      animate="visible"
    >
      {tabs.map((t) => {
        const isActive = activeId === t.id
        const isDashboard = t.kind === 'dashboard'
        const needsDivider = prevCategory !== null && prevCategory !== t.category
        prevCategory = t.category

        const activeColor = isDashboard ? colors.value : colors.active
        const tabColor = isActive ? activeColor : colors.dim

        return (
          <motion.div
            key={t.id}
            className="flex items-stretch"
            variants={reducedMotion ? undefined : tabVariants}
          >
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
                height: 30,
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
              {/* Icon with settle spring on activation */}
              <motion.div
                key={isActive ? 'active' : 'idle'}
                initial={isActive && !reducedMotion ? { scale: 1.12 } : false}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 500, damping: 25 }}
                style={{ display: 'flex' }}
              >
                <t.icon style={{ width: 14, height: 14, strokeWidth: 1.8 }} />
              </motion.div>
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
                      : { duration: 0.22, ease: [0.4, 0, 0.2, 1] as const }
                  }
                />
              )}
            </button>
          </motion.div>
        )
      })}
    </motion.div>
  )
}
