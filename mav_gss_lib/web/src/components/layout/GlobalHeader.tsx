import { useState, useEffect } from 'react'
import { Satellite, Settings, HelpCircle, FileText, Maximize, Minimize, Camera, ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { colors } from '@/lib/colors'
import type { PluginPageDef } from '@/plugins/registry'

interface GlobalHeaderProps {
  missionName: string
  version: string
  page?: string | null
  plugins?: PluginPageDef[]
  onPluginClick?: (id: string) => void
  onBackClick?: () => void
  onLogsClick: () => void
  onConfigClick: () => void
  onHelpClick: () => void
}

export function GlobalHeader({
  missionName,
  version,
  page, plugins, onPluginClick, onBackClick,
  onLogsClick, onConfigClick, onHelpClick,
}: GlobalHeaderProps) {
  const [isFullscreen, setIsFullscreen] = useState(!!document.fullscreenElement)
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const onChange = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen()
    else document.documentElement.requestFullscreen()
  }
  const utcDate = now.toISOString().slice(0, 10)
  const utcTime = now.toISOString().slice(11, 19)
  const localDate = now.toLocaleDateString('en-CA')
  const localTime = now.toLocaleTimeString('en-GB', { hour12: false })
  const tz = (Intl.DateTimeFormat().resolvedOptions().timeZone.split('/').pop() ?? 'local').replace(/_/g, ' ')

  const activePlugin = page && plugins ? plugins.find(p => p.id === page) : null

  return (
    <header className="flex items-center h-10 px-4 border-b shrink-0" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgApp }}>
      {/* Back button when on plugin page */}
      {page && onBackClick ? (
        <Button variant="ghost" size="sm" onClick={onBackClick} className="h-7 px-2 gap-1.5 text-[11px] mr-2" style={{ color: colors.dim }}>
          <ArrowLeft className="size-3.5" />
          Back
        </Button>
      ) : null}

      {/* Brand */}
      <div className="usc-brand flex items-center gap-2 mr-6 cursor-default">
        <Satellite className="usc-icon size-4 transition-colors" style={{ color: colors.label }} />
        <span className="usc-maveric font-bold text-sm tracking-wide transition-colors" style={{ color: colors.value }}>{missionName}</span>
        <span className="usc-gss font-bold text-sm tracking-wide transition-colors" style={{ color: colors.value }}>GSS</span>
        <span className="text-[11px]" style={{ color: colors.dim }}>v{version}</span>
        {activePlugin && (
          <>
            <span className="text-[11px]" style={{ color: colors.sep }}>/</span>
            <span className="text-[11px] font-medium" style={{ color: colors.label }}>{activePlugin.name}</span>
          </>
        )}
      </div>

      {/* Clock */}
      <div className="flex items-center gap-3 mr-6 tabular-nums text-[11px]">
        <span style={{ color: colors.value }}>{localDate} {localTime} <span className="font-light" style={{ color: colors.dim }}>{tz}</span></span>
        <span className="font-light" style={{ color: colors.dim }}>{utcDate} {utcTime} UTC</span>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Nav buttons */}
      <div className="flex items-center gap-0.5">
        {/* Plugin buttons — shown when not on a plugin page */}
        {!page && plugins && plugins.length > 0 && plugins.map(p => (
          <Button
            key={p.id}
            variant="ghost"
            size="sm"
            onClick={() => onPluginClick?.(p.id)}
            className="h-7 px-2 gap-1.5 text-[11px]"
            style={{ color: colors.dim }}
          >
            <Camera className="size-3.5" />
            {p.name}
          </Button>
        ))}
        {!page && (
          <>
            <Button variant="ghost" size="sm" onClick={onLogsClick} className="h-7 px-2 gap-1.5 text-[11px]" style={{ color: colors.dim }}>
              <FileText className="size-3.5" />
              Logs
            </Button>
            <Button variant="ghost" size="sm" onClick={onConfigClick} className="h-7 px-2 gap-1.5 text-[11px]" style={{ color: colors.dim }}>
              <Settings className="size-3.5" />
              Config
            </Button>
            <Button variant="ghost" size="sm" onClick={onHelpClick} className="h-7 px-2 gap-1.5 text-[11px]" style={{ color: colors.dim }}>
              <HelpCircle className="size-3.5" />
              Help
            </Button>
          </>
        )}
        <Button variant="ghost" size="icon" onClick={toggleFullscreen} className="size-7 btn-feedback" title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}>
          {isFullscreen
            ? <Minimize className="size-3.5" style={{ color: colors.dim }} />
            : <Maximize className="size-3.5" style={{ color: colors.dim }} />
          }
        </Button>
      </div>
    </header>
  )
}
