import type { UpdatePhase } from '@/lib/types'

export const PHASE_LABELS: Record<UpdatePhase, string> = {
  git_pull:  'git pull',
  countdown: 'restart in',
  restart:   'restart',
}

export const PHASE_ORDER: UpdatePhase[] = ['git_pull', 'countdown', 'restart']

// Welcome-screen slate accent (kept separate from colors.active cyan so the
// rest of the app's "selection / live context" semantic tone stays untouched).
export const SLATE_ACCENT = '#C8D0DC'
export const USC_GOLD     = '#FFCC00'
