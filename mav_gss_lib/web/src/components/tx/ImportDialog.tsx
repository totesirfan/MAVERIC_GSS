import { useEffect, useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { FileUp, FileText, Check, ChevronRight, Shield, Timer } from 'lucide-react'
import { colors } from '@/lib/colors'
import { col } from '@/lib/columns'
import { PtypeBadge } from '@/components/shared/PtypeBadge'
import { authFetch } from '@/lib/auth'
import type { TxColumnDef, DetailBlock } from '@/lib/types'

interface ImportDialogProps {
  open: boolean
  onClose: () => void
  onImported: () => void
  txColumns: TxColumnDef[]
}

interface ImportFile {
  name: string
  path: string
  size: number
}

interface PreviewItem {
  type: string
  display?: {
    title: string
    subtitle?: string
    row?: Record<string, string | number>
    detail_blocks?: DetailBlock[]
  }
  guard?: boolean
  size?: number
  delay_ms?: number
}

const springConfig = { type: 'spring' as const, stiffness: 500, damping: 30, mass: 0.8 }

export function ImportDialog({ open, onClose, onImported, txColumns }: ImportDialogProps) {
  const [files, setFiles] = useState<ImportFile[]>([])
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [preview, setPreview] = useState<PreviewItem[]>([])
  const [skipped, setSkipped] = useState(0)
  const [loading, setLoading] = useState(false)
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<{ loaded: number; skipped: number } | null>(null)

  useEffect(() => {
    if (open) {
      setResult(null)
      setSelectedFile(null)
      setPreview([])
      fetch('/api/import-files').then(r => r.json()).then(setFiles).catch(() => setFiles([]))
    }
  }, [open])

  const visibleColumns = useMemo(() => {
    return txColumns.filter(col => {
      if (!col.hide_if_all?.length) return true
      const suppressSet = new Set(col.hide_if_all)
      return !preview.every(item => {
        if (item.type === 'delay') return true
        return suppressSet.has(String(item.display?.row?.[col.id] ?? ''))
      })
    })
  }, [txColumns, preview])

  async function loadPreview(filename: string) {
    setSelectedFile(filename)
    setLoading(true)
    setResult(null)
    try {
      const res = await fetch(`/api/import/${encodeURIComponent(filename)}/preview`)
      const data = await res.json()
      setPreview(data.items ?? [])
      setSkipped(data.skipped ?? 0)
    } catch {
      setPreview([])
      setSkipped(0)
    }
    setLoading(false)
  }

  async function doImport() {
    if (!selectedFile) return
    setImporting(true)
    try {
      const res = await authFetch(`/api/import/${encodeURIComponent(selectedFile)}`, { method: 'POST' })
      const data = await res.json()
      setResult(data)
      onImported()
      onClose()
    } catch {
      setResult({ loaded: 0, skipped: 0 })
    }
    setImporting(false)
  }

  if (!open) return null

  return (
    <>
      <motion.div
        className="fixed inset-0 z-40 frosted-backdrop"
        style={{ backgroundColor: 'rgba(0,0,0,0.7)' }}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
      />
      <div className="fixed inset-x-8 top-12 bottom-12 z-50 rounded-xl border overflow-hidden flex max-w-2xl mx-auto shadow-overlay"
        style={{ borderColor: colors.borderStrong, backgroundColor: colors.bgPanelRaised }}>

        {/* Left: file list */}
        <div className="w-56 shrink-0 border-r flex flex-col" style={{ borderColor: colors.borderSubtle }}>
          <div className="flex items-center gap-2 px-3 py-2.5 border-b shrink-0" style={{ borderColor: colors.borderSubtle }}>
            <FileUp className="size-4" style={{ color: colors.label }} />
            <span className="text-xs font-bold" style={{ color: colors.label }}>Import</span>
            <div className="flex-1" />
            <button onClick={onClose} className="text-xs hover:bg-white/5 rounded px-1" style={{ color: colors.dim }}>✕</button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {files.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-2 p-4" style={{ color: colors.dim }}>
                <FileText className="size-6" />
                <span className="text-[11px] text-center">No files in generated_commands/</span>
              </div>
            ) : (
              files.map((f) => {
                const active = selectedFile === f.name
                return (
                  <button
                    key={f.name}
                    onClick={() => loadPreview(f.name)}
                    className="flex items-center gap-2 w-full text-left px-3 py-2 text-xs hover:bg-white/[0.04] color-transition"
                    style={{
                      backgroundColor: active ? `${colors.label}11` : undefined,
                      borderLeft: active ? `2px solid ${colors.label}` : '2px solid transparent',
                    }}
                  >
                    <FileText className="size-3.5 shrink-0" style={{ color: active ? colors.label : colors.dim }} />
                    <div className="flex-1 min-w-0">
                      <div className="font-mono truncate" style={{ color: active ? colors.label : colors.value }}>{f.name}</div>
                      <div className="text-[11px]" style={{ color: colors.dim }}>{(f.size / 1024).toFixed(1)} KB</div>
                    </div>
                    <ChevronRight className="size-3 shrink-0" style={{ color: colors.dim }} />
                  </button>
                )
              })
            )}
          </div>
        </div>

        {/* Right: preview */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <AnimatePresence mode="wait">
            {!selectedFile ? (
              <motion.div
                key="empty"
                className="flex-1 flex items-center justify-center"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <span className="text-xs" style={{ color: colors.dim }}>Select a file to preview</span>
              </motion.div>
            ) : loading ? (
              <motion.div
                key="loading"
                className="flex-1 flex items-center justify-center"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <span className="text-xs" style={{ color: colors.dim }}>Loading preview...</span>
              </motion.div>
            ) : (
              <motion.div
                key={selectedFile}
                className="flex-1 flex flex-col overflow-hidden"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                transition={springConfig}
              >
                {/* Preview header */}
                <div className="flex items-center justify-between px-3 py-2 border-b shrink-0" style={{ borderColor: colors.borderSubtle }}>
                  <span className="text-xs font-mono" style={{ color: colors.value }}>{selectedFile}</span>
                  <span className="text-[11px]" style={{ color: colors.dim }}>
                    {preview.length} command{preview.length !== 1 ? 's' : ''}
                    {skipped > 0 && <span style={{ color: colors.warning }}> · {skipped} skipped</span>}
                  </span>
                </div>

                {/* Result banner */}
                {result && (
                  <div className="flex items-center gap-2 px-3 py-1.5 border-b animate-slide-in" style={{ borderColor: colors.borderSubtle, backgroundColor: `${colors.success}11` }}>
                    <Check className="size-3.5" style={{ color: colors.success }} />
                    <span className="text-xs" style={{ color: colors.success }}>
                      Loaded {result.loaded} commands{result.skipped > 0 ? `, skipped ${result.skipped}` : ''}
                    </span>
                  </div>
                )}

                {/* Command list */}
                <div className="flex-1 overflow-y-auto">
                  {preview.map((item, i) => (
                    <div key={i} className="flex items-center gap-2 px-3 py-1 text-xs border-b" style={{ borderColor: colors.borderSubtle }}>
                      <span className={`${col.num} text-right shrink-0 tabular-nums`} style={{ color: colors.dim }}>{i + 1}</span>
                      {item.type === 'delay' ? (
                        <>
                          <Timer className="size-3 shrink-0" style={{ color: colors.warning }} />
                          <span style={{ color: colors.warning }}>{((item.delay_ms ?? 0) / 1000).toFixed(1)}s delay</span>
                        </>
                      ) : visibleColumns.length > 0 ? (
                        <>
                          {visibleColumns.map(c => {
                            const val = item.display?.row?.[c.id] ?? ''
                            return (
                              <span key={c.id} className={`${c.width ?? ''} ${c.flex ? 'flex-1 min-w-0 truncate' : 'shrink-0'}`}>
                                {c.badge ? <PtypeBadge ptype={val} /> :
                                 c.id === 'cmd' ? (
                                   <span className="shrink-0 px-1.5 py-0.5 rounded text-[11px] font-semibold" style={{ color: colors.value, backgroundColor: 'rgba(255,255,255,0.06)' }}>
                                     {String(val)}
                                   </span>
                                 ) : <span style={{ color: colors.dim }}>{val}</span>}
                              </span>
                            )
                          })}
                          {item.guard && <Shield className="size-3 shrink-0" style={{ color: colors.warning }} />}
                        </>
                      ) : (
                        <>
                          <span className="shrink-0 px-1.5 py-0.5 rounded text-[11px] font-semibold" style={{ color: colors.value, backgroundColor: 'rgba(255,255,255,0.06)' }}>{item.display?.title ?? '?'}</span>
                          {item.guard && <Shield className="size-3 shrink-0" style={{ color: colors.warning }} />}
                        </>
                      )}
                    </div>
                  ))}
                </div>

                {/* Confirm bar */}
                {!result && (
                  <div className="flex items-center justify-between px-3 py-2 border-t shrink-0" style={{ borderColor: colors.borderSubtle }}>
                    <button onClick={() => setSelectedFile(null)} className="text-xs px-2 py-1 rounded border btn-feedback"
                      style={{ color: colors.dim, borderColor: colors.borderSubtle }}>
                      Back
                    </button>
                    <button
                      onClick={doImport}
                      disabled={importing || preview.length === 0}
                      className="text-xs px-4 py-1 rounded font-bold btn-feedback disabled:opacity-30"
                      style={{ backgroundColor: colors.success, color: colors.bgApp }}
                    >
                      {importing ? 'Importing...' : `Import ${preview.length} commands`}
                    </button>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </>
  )
}
