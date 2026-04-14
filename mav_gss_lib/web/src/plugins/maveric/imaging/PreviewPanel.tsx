import { useMemo } from 'react'
import { Image as ImageIcon } from 'lucide-react'
import { colors } from '@/lib/colors'

interface PreviewPanelProps {
  selectedFile: string
  /** Monotonically-increasing version number; parent bumps it when it wants the preview to refresh. */
  version: number
  hasFiles: boolean
}

/**
 * JPEG preview for the selected image. Cache busting is driven by the parent's
 * `version` number (typically debounced from chunk-arrival count) so the image
 * element doesn't thrash on every individual chunk during a 10s-paced download.
 */
export function PreviewPanel({ selectedFile, version, hasFiles }: PreviewPanelProps) {
  const imgSrc = useMemo(() => {
    if (!selectedFile) return ''
    return `/api/plugins/imaging/preview/${encodeURIComponent(selectedFile)}?v=${version}`
  }, [selectedFile, version])

  return (
    <div
      className="flex-1 rounded-lg border overflow-hidden flex flex-col"
      style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}
    >
      <div
        className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0"
        style={{ borderColor: colors.borderSubtle }}
      >
        <ImageIcon className="size-3.5" style={{ color: colors.dim }} />
        <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.label }}>
          Preview
        </span>
        {selectedFile && (
          <span className="text-[11px] font-mono" style={{ color: colors.dim }}>{selectedFile}</span>
        )}
      </div>
      <div className="flex-1 relative min-h-0 p-4">
        {imgSrc ? (
          <img
            src={imgSrc}
            alt={selectedFile}
            className="absolute inset-4 w-[calc(100%-2rem)] h-[calc(100%-2rem)] object-contain"
            style={{ imageRendering: 'auto' }}
            onError={() => {}}
          />
        ) : (
          <div
            className="absolute inset-0 flex items-center justify-center text-[11px]"
            style={{ color: colors.dim }}
          >
            {hasFiles ? 'Select a file to preview' : 'No images yet'}
          </div>
        )}
      </div>
    </div>
  )
}
