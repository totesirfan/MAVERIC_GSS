import { useMemo } from 'react'
import { Grid3x3, ChevronDown, Trash2 } from 'lucide-react'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { colors } from '@/lib/colors'
import { formatMissingRanges, type ImagingFileStatus } from './helpers'

interface ProgressPanelProps {
  files: ImagingFileStatus[]
  selectedFile: string
  selectedProgress: ImagingFileStatus | undefined
  chunks: number[]
  onSelect: (filename: string) => void
  onDelete: (filename: string) => void
}

/**
 * File selector + per-chunk progress grid. Uses shape redundancy
 * (solid filled disc vs hollow red ring) so missing chunks are
 * distinguishable without relying on color alone (HFDS 9.3.6).
 */
export function ProgressPanel({
  files, selectedFile, selectedProgress, chunks, onSelect, onDelete,
}: ProgressPanelProps) {
  const chunkSet = useMemo(() => new Set(chunks), [chunks])
  const prog = selectedProgress
  const total = prog?.total ?? 0

  const missingChunks = useMemo(() => {
    if (!total) return [] as number[]
    const missing: number[] = []
    for (let i = 0; i < total; i++) if (!chunkSet.has(i)) missing.push(i)
    return missing
  }, [total, chunkSet])

  return (
    <div
      className="rounded-lg border overflow-hidden shrink-0"
      style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}
    >
      <div
        className="flex items-center gap-2 px-3 py-1.5 border-b"
        style={{ borderColor: colors.borderSubtle }}
      >
        <Grid3x3 className="size-3.5" style={{ color: colors.dim }} />
        <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.label }}>
          Progress
        </span>
        <div className="flex-1" />
        {files.length > 0 && (
          <>
            <DropdownMenu>
              <DropdownMenuTrigger
                className="flex items-center gap-1 border rounded px-2 py-0.5 text-[11px] outline-none hover:bg-white/[0.04]"
                style={{ borderColor: colors.borderSubtle, color: colors.value }}
              >
                {selectedFile || 'Select file'}
                {selectedFile && (() => {
                  const f = files.find(f => f.filename === selectedFile)
                  if (!f) return null
                  return (
                    <span style={{ color: f.complete ? colors.success : colors.dim }}>
                      {f.complete ? '(complete)' : f.total ? `(${f.received}/${f.total})` : ''}
                    </span>
                  )
                })()}
                <ChevronDown className="size-3" style={{ color: colors.dim }} />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-[240px]">
                {files.map(f => (
                  <DropdownMenuItem
                    key={f.filename}
                    onClick={() => onSelect(f.filename)}
                    className="text-[11px] font-mono flex items-center justify-between gap-2"
                  >
                    <span className="flex-1 truncate">{f.filename}</span>
                    <span style={{ color: f.complete ? colors.success : colors.dim }}>
                      {f.complete ? 'complete' : f.total ? `${f.received}/${f.total}` : '...'}
                    </span>
                    <button
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => { e.stopPropagation(); onDelete(f.filename) }}
                      className="p-0.5 rounded hover:bg-white/[0.08]"
                      title={`Delete ${f.filename}`}
                    >
                      <Trash2 className="size-3" style={{ color: colors.danger }} />
                    </button>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            {selectedFile && (
              <button
                onClick={() => onDelete(selectedFile)}
                className="p-1 rounded border hover:bg-white/[0.04]"
                style={{ borderColor: colors.borderSubtle }}
                title={`Delete ${selectedFile}`}
              >
                <Trash2 className="size-3" style={{ color: colors.danger }} />
              </button>
            )}
          </>
        )}
      </div>

      {prog && prog.total ? (
        <div className="px-3 py-2">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-[11px] font-medium" style={{ color: colors.value }}>
              {prog.received} / {prog.total}
            </span>
            <span className="text-[11px]" style={{ color: colors.dim }}>
              ({Math.round((prog.received / prog.total) * 100)}%)
            </span>
            <span
              className="text-[11px] ml-auto"
              style={{ color: prog.complete ? colors.success : missingChunks.length > 0 ? colors.warning : colors.active }}
            >
              {prog.complete ? 'Complete' : missingChunks.length > 0 ? `${missingChunks.length} missing` : 'Receiving...'}
            </span>
          </div>
          <div className="flex flex-wrap gap-0.5">
            {Array.from({ length: prog.total }, (_, i) => {
              const received = chunkSet.has(i)
              // Shape redundancy (HFDS 9.3.6): received = filled green disc,
              // missing = hollow red ring. Distinguishable without color.
              return (
                <div
                  key={i}
                  className="rounded-full"
                  style={{
                    width: 8,
                    height: 8,
                    backgroundColor: received ? colors.success : 'transparent',
                    border: received ? 'none' : `1px solid ${colors.danger}`,
                    boxSizing: 'border-box',
                  }}
                  title={`Chunk ${i}${received ? '' : ' (missing)'}`}
                />
              )
            })}
          </div>
          {missingChunks.length > 0 && !prog.complete && (
            <div
              className="text-[11px] font-mono mt-1.5 flex flex-wrap gap-x-1.5 gap-y-0.5"
              style={{ color: colors.dim }}
            >
              <span style={{ color: colors.danger }}>Missing:</span>
              {formatMissingRanges(missingChunks).map((range, i) => (
                <span key={i} style={{ color: colors.value }}>{range}</span>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="px-3 py-3 text-[11px]" style={{ color: colors.dim }}>
          {files.length === 0 ? 'No active transfers' : 'Waiting for chunk count...'}
        </div>
      )}
    </div>
  )
}
