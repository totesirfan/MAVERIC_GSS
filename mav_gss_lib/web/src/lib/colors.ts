/* ── MAVERIC GSS Semantic Color System ────────────────────────────
 *
 * All colors reference CSS custom properties defined in index.css.
 * Semantic meanings:
 *   danger  = failure, timeout, invalid, hard error        (red)
 *   warning = caution, guarded, degraded, hazardous        (yellow/amber)
 *   info    = acknowledgement, advisory, informational     (blue)
 *   success = confirmed nominal, healthy, valid result     (green)
 *   active  = selection, live context, focus               (cyan)
 *   neutral = disabled, unavailable, stale, unknown        (gray)
 */

// ── Base surface + text tokens (resolved from CSS vars) ──────────

export const colors = {
  // Text hierarchy
  textPrimary:   '#E5E5E5',
  textSecondary: '#A0A0A0',
  textMuted:     '#8A8A8A',
  textDisabled:  '#777777',

  // Surfaces (pure black)
  bgApp:         '#080808',
  bgPanelRaised: '#151515',

  // Borders
  borderSubtle:  '#222222',
  borderStrong:  '#333333',

  // Semantic state colors (restrained)
  danger:        '#FF3838',
  dangerFill:    '#1A0E0E',
  warning:       '#E8B83A',
  warningFill:   '#1A1508',
  info:          '#5AA8F0',
  infoFill:      '#0E1418',
  success:       '#3CC98E',
  successFill:   '#0C1612',
  active:        '#30C8E0',
  activeFill:    '#0C1315',
  neutral:       '#888888',
  neutralFill:   '#141414',

  // Legacy aliases (used widely, mapped to new semantic names)
  label:   '#30C8E0',   // active/cyan — selection, live context
  value:   '#E5E5E5',   // text-primary
  error:   '#FF3838',   // danger
  dim:     '#8A8A8A',   // text-muted
  sep:     '#777777',   // text-disabled (5.2:1 contrast on #080808)
  bgBase:  '#080808',   // bg-app
  bgPanel: '#0E0E0E',   // bg-panel
  bgCard:  'rgba(255,255,255,0.02)',

  // Modal / dialog backdrop overlays
  modalBackdrop:      'rgba(0, 0, 0, 0.7)',
  modalBackdropHeavy: 'rgba(8, 8, 8, 0.8)',

  // Frame type colors (muted)
  frameAx25:  '#6690B8',
  frameGolay: '#50A898',

  // Uplink echo flag color (dev/debug — distinct from semantic tones)
  ulColor: '#A07CC8',
} as const

// ── Badge label → semantic tone mapping ────────────────────────

export type SemanticTone = 'danger' | 'warning' | 'info' | 'success' | 'active' | 'neutral'

export const badgeToneMap: Record<string, SemanticTone> = {
  ACK:     'info',
  RES:     'success',
  CMD:     'neutral',
  REQ:     'neutral',
  TLM:     'active',
  FILE:    'neutral',
  ERR:     'danger',
  FAIL:    'danger',
  TIMEOUT: 'danger',
  NACK:    'danger',
  GUARD:   'warning',
  NONE:    'neutral',
} as const

/** Get the semantic tone for a mission-provided badge label. */
export function labelTone(label: string | number): SemanticTone {
  return badgeToneMap[String(label).toUpperCase()] ?? 'neutral'
}

/** Semantic tone → foreground color */
export const toneColor: Record<SemanticTone, string> = {
  danger:  colors.danger,
  warning: colors.warning,
  info:    colors.info,
  success: colors.success,
  active:  colors.active,
  neutral: colors.neutral,
}

/** Semantic tone → fill/background color */
export const toneFill: Record<SemanticTone, string> = {
  danger:  colors.dangerFill,
  warning: colors.warningFill,
  info:    colors.infoFill,
  success: colors.successFill,
  active:  colors.activeFill,
  neutral: colors.neutralFill,
}

/** Semantic tone → border color (30% opacity — subtle) */
export const toneBorder: Record<SemanticTone, string> = {
  danger:  `${colors.danger}4D`,
  warning: `${colors.warning}4D`,
  info:    `${colors.info}4D`,
  success: `${colors.success}4D`,
  active:  `${colors.active}4D`,
  neutral: `${colors.neutral}4D`,
}

export function frameColor(frame: string): string {
  const f = (frame || '').toUpperCase()
  if (f.includes('AX.25') || f.includes('AX25')) return colors.frameAx25
  if (f.includes('GOLAY') || f.includes('ASM')) return colors.frameGolay
  return colors.danger
}

/** Override tone for RES packets based on payload content */
export function getResponseTone(response: {
  type?: string
  ok?: boolean
  severity?: 'info' | 'warning' | 'danger'
  parseState?: 'ok' | 'unknown' | 'missing'
}): SemanticTone {
  if (response.parseState === 'unknown' || response.parseState === 'missing') return 'neutral'
  if (response.severity === 'danger' || response.ok === false) return 'danger'
  if (response.severity === 'warning') return 'warning'
  if (response.type === 'ACK') return 'info'
  if (response.type === 'RES') return 'success'
  return 'neutral'
}
