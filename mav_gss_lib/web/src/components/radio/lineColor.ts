import { colors } from '@/lib/colors'

/**
 * Classify a GNU Radio log line by its prefix and assign a color.
 * Strict: only the canonical prefixes trigger semantic colors;
 * everything else is rendered with the secondary text tone.
 */
export function lineColor(line: string): string {
  // Strip leading ISO timestamp the supervisor adds: "2026-04-30T17:35:42Z "
  const body = line.replace(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\s/, '')

  // GR canonical prefixes
  if (body.startsWith('[ERROR]') || body.startsWith('gr::log :ERROR')) return colors.danger
  if (body.startsWith('[WARNING]') || body.startsWith('gr::log :WARN')) return colors.warning
  if (body.startsWith('[INFO]') || body.startsWith('gr::log :INFO')) return colors.info
  if (body.startsWith('[DEBUG]')) return colors.textMuted

  // Python tracebacks — color the whole frame as danger
  if (
    body.startsWith('Traceback (') ||
    /^\s*File "/.test(body) ||
    /^[A-Za-z][A-Za-z0-9_.]*Error\b/.test(body) ||
    /^[A-Za-z][A-Za-z0-9_.]*Exception\b/.test(body)
  ) return colors.danger

  // UHD / USRP overflow & underflow markers
  if (/^[OUuS]\b/.test(body) && body.length <= 4) return colors.warning

  return colors.textSecondary
}
