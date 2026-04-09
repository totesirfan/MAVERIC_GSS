import { useState } from 'react'

interface UseRxTogglesOptions {
  externalShowHex?: boolean
  externalShowFrame?: boolean
  externalShowWrapper?: boolean
  externalHideUplink?: boolean
  onToggleHex?: () => void
  onToggleFrame?: () => void
  onToggleWrapper?: () => void
  onToggleUplink?: () => void
}

export function useRxToggles(opts: UseRxTogglesOptions = {}) {
  const [localShowHex, setLocalShowHex] = useState(false)
  const [localShowFrame, setLocalShowFrame] = useState(false)
  const [localShowWrapper, setLocalShowWrapper] = useState(false)
  const [localHideUplink, setLocalHideUplink] = useState(true)

  return {
    showHex: opts.externalShowHex ?? localShowHex,
    showFrame: opts.externalShowFrame ?? localShowFrame,
    showWrapper: opts.externalShowWrapper ?? localShowWrapper,
    hideUplink: opts.externalHideUplink ?? localHideUplink,
    toggleHex: opts.onToggleHex ?? (() => setLocalShowHex(v => !v)),
    toggleFrame: opts.onToggleFrame ?? (() => setLocalShowFrame(v => !v)),
    toggleWrapper: opts.onToggleWrapper ?? (() => setLocalShowWrapper(v => !v)),
    toggleUplink: opts.onToggleUplink ?? (() => setLocalHideUplink(v => !v)),
  }
}
