import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { Send, Image, Grid3x3, FileText, Download, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { colors } from '@/lib/colors'
import { showToast } from '@/components/shared/StatusToast'
import { GssInput } from '@/components/ui/gss-input'
import { usePluginServices } from '@/hooks/usePluginServices'

// ── Types ───────────────────────────────────────────────────────────

interface ImagingPacket {
  num: number
  time: string
  cmd: string
  args: string
}

interface ImagingProgress {
  filename: string
  received: number
  total: number | null
  complete: boolean
}

interface FileStatus {
  filename: string
  received: number
  total: number | null
  complete: boolean
}

/** Collapse missing chunk indices into ranges: [5,6,7,10,15] → ["5-7","10","15"] */
function formatMissingRanges(missing: number[]): string[] {
  if (missing.length === 0) return []
  const ranges: string[] = []
  let start = missing[0]
  let end = start
  for (let i = 1; i < missing.length; i++) {
    if (missing[i] === end + 1) {
      end = missing[i]
    } else {
      ranges.push(start === end ? `${start}` : `${start}–${end}`)
      start = missing[i]
      end = start
    }
  }
  ranges.push(start === end ? `${start}` : `${start}–${end}`)
  return ranges
}

// ── Main Component ──────────────────────────────────────────────────

export default function ImagingPage() {
  const { packets: rxPackets, config, queueCommand, txConnected, subscribeRxCustom, sessionResetGen, fetchSchema } = usePluginServices()

  const [packets, setPackets] = useState<ImagingPacket[]>([])
  const [progress, setProgress] = useState<Record<string, ImagingProgress>>({})
  const [selectedFile, setSelectedFile] = useState<string>('')
  const [files, setFiles] = useState<FileStatus[]>([])
  const [chunks, setChunks] = useState<number[]>([])
  const [receiving, setReceiving] = useState(false)
  const receivingTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const listEndRef = useRef<HTMLDivElement>(null)

  // TX form state
  const [cntFilename, setCntFilename] = useState('')
  const [cntChunkSize, setCntChunkSize] = useState('')
  const [getFilename, setGetFilename] = useState('')
  const [getStartChunk, setGetStartChunk] = useState('')
  const [getNumChunks, setGetNumChunks] = useState('')
  const [destNode, setDestNode] = useState('')
  const [nodes, setNodes] = useState<string[]>([])

  // Schema fetch via plugin services
  const [schema, setSchema] = useState<Record<string, Record<string, unknown>> | null>(null)
  useEffect(() => {
    fetchSchema().then(setSchema).catch(() => {})
  }, [fetchSchema])

  // Resolve imaging-capable nodes from config + schema
  useEffect(() => {
    if (!config || !schema) return
    const imgCmd = schema?.img_get_chunk ?? schema?.img_cnt_chunks
    const allowedNodes: string[] = (imgCmd?.nodes as string[]) ?? []
    const nodeMap: Record<string, string> = config?.nodes ?? {}
    let nodeNames: string[]
    if (allowedNodes.length > 0) {
      nodeNames = allowedNodes.filter(n => Object.values(nodeMap).includes(n))
    } else {
      const gsNode = config?.general?.gs_node ?? ''
      nodeNames = Object.values(nodeMap).filter((n): n is string => n !== gsNode)
    }
    setNodes(nodeNames)
    if (nodeNames.length > 0) setDestNode(prev => prev || nodeNames[0])
  }, [config, schema])

  // Fetch initial status
  useEffect(() => {
    fetch('/api/plugins/imaging/status')
      .then(r => r.json())
      .then(data => {
        if (data.files) {
          setFiles(data.files)
          const prog: Record<string, ImagingProgress> = {}
          for (const f of data.files) prog[f.filename] = f
          setProgress(prog)
          if (!selectedFile && data.files.length > 0) {
            setSelectedFile(data.files[0].filename)
          }
        }
      })
      .catch(() => {})
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Subscribe to custom RX messages (imaging_progress)
  useEffect(() => {
    return subscribeRxCustom((msg) => {
      if (msg.type === 'imaging_progress') {
        const p = msg as unknown as ImagingProgress
        setProgress(prev => ({ ...prev, [p.filename]: p }))
        setFiles(prev => {
          const existing = prev.find(f => f.filename === p.filename)
          if (existing) {
            return prev.map(f => f.filename === p.filename ? { ...f, received: p.received, total: p.total, complete: p.complete } : f)
          }
          return [...prev, { filename: p.filename, received: p.received, total: p.total, complete: p.complete }]
        })
        setSelectedFile(prev => prev || p.filename)
      }
    })
  }, [subscribeRxCustom])

  // Filter imaging packets from shared RX stream
  const imagingPackets = useMemo(() => {
    return rxPackets.filter(p => {
      const cmd = String(p._rendering?.row?.values?.cmd ?? '')
      return cmd.startsWith('img_cnt_chunks') || cmd.startsWith('img_get_chunk')
    }).map(p => ({
      num: p.num,
      time: p.time,
      cmd: String(p._rendering?.row?.values?.cmd ?? '').split(' ')[0],
      args: String(p._rendering?.row?.values?.cmd ?? '').split(' ').slice(1).join(' '),
    }))
  }, [rxPackets])

  // Session reset clears all imaging state and refetches fresh status
  useEffect(() => {
    if (sessionResetGen > 0) {
      setPackets([])
      setReceiving(false)
      setProgress({})
      setSelectedFile('')
      setFiles([])
      setChunks([])
      // Refetch current imaging status for the new session
      fetch('/api/plugins/imaging/status')
        .then(r => r.json())
        .then(data => {
          if (data.files) {
            setFiles(data.files)
            const prog: Record<string, ImagingProgress> = {}
            for (const f of data.files) prog[f.filename] = f
            setProgress(prog)
            if (data.files.length > 0) setSelectedFile(data.files[0].filename)
          }
        })
        .catch(() => {})
    }
  }, [sessionResetGen])

  // Sync imaging packets to local state (for receiving indicator)
  const prevImagingCount = useRef(0)
  useEffect(() => {
    if (imagingPackets.length > prevImagingCount.current) {
      setPackets(imagingPackets.slice(-500))
      setReceiving(true)
      if (receivingTimer.current) clearTimeout(receivingTimer.current)
      receivingTimer.current = setTimeout(() => setReceiving(false), 1500)
    }
    prevImagingCount.current = imagingPackets.length
  }, [imagingPackets])

  // Auto-scroll RX log
  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [packets.length])

  // Derive image preview URL from selected file + progress
  const selectedProgress = selectedFile ? progress[selectedFile] : undefined
  const imgSrc = useMemo(() => {
    if (!selectedFile) return ''
    // selectedProgress triggers recalculation when chunks arrive
    return `/api/plugins/imaging/preview/${encodeURIComponent(selectedFile)}?t=${Date.now()}`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFile, selectedProgress?.received])

  // Fetch chunks for selected file when progress changes
  useEffect(() => {
    if (!selectedFile) { setChunks([]); return }
    fetch(`/api/plugins/imaging/chunks/${encodeURIComponent(selectedFile)}`)
      .then(r => r.json())
      .then(data => setChunks(data.chunks ?? []))
      .catch(() => setChunks([]))
  }, [selectedFile, selectedProgress?.received])

  const queueCmd = useCallback((cmdId: string, args: Record<string, string>) => {
    if (!txConnected) {
      showToast('TX not connected', 'error', 'tx')
      return
    }
    if (!destNode) {
      showToast('No destination node selected', 'error', 'tx')
      return
    }
    queueCommand({
      cmd_id: cmdId,
      args,
      dest: destNode,
      echo: (schema?.[cmdId] as Record<string, unknown>)?.echo as string ?? 'NONE',
      ptype: (schema?.[cmdId] as Record<string, unknown>)?.ptype as string ?? 'CMD',
    })
  }, [destNode, txConnected, queueCommand, schema])

  const handleCntChunks = () => {
    if (!cntFilename.trim()) return
    queueCmd('img_cnt_chunks', { Filename: cntFilename.trim(), 'Chunk Size': cntChunkSize.trim() || '150' })
  }

  const handleGetChunk = () => {
    if (!getFilename.trim() || !getStartChunk.trim()) return
    queueCmd('img_get_chunk', { Filename: getFilename.trim(), 'Start Chunk': getStartChunk.trim(), 'Num Chunks': getNumChunks.trim() || '1' })
  }

  const prog = selectedFile ? progress[selectedFile] : null

  return (
    <div className="flex-1 flex overflow-hidden p-4 gap-4">
      {/* ── Left Column ────────────────────────────────── */}
      <div className="flex flex-col gap-4 shrink-0" style={{ width: 400 }}>
        {/* RX Log */}
        <div
          className="flex-1 flex flex-col rounded-lg border overflow-hidden"
          style={{
            borderColor: receiving ? `${colors.success}55` : colors.borderSubtle,
            backgroundColor: colors.bgPanel,
            transition: 'border-color 160ms ease',
          }}
        >
          <div
            className={`flex items-center gap-2 px-3 py-1.5 border-b shrink-0 ${receiving ? 'animate-sweep-green' : ''}`}
            style={{
              borderColor: colors.borderSubtle,
              backgroundColor: receiving ? `${colors.success}08` : 'transparent',
              transition: 'background-color 160ms ease',
            }}
          >
            {receiving ? (
              <Download className="size-3.5" style={{ color: colors.success }} />
            ) : (
              <FileText className="size-3.5" style={{ color: colors.dim }} />
            )}
            <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: receiving ? colors.success : colors.label }}>
              {receiving ? 'Receiving' : 'RX Log'}
            </span>
            <span className="text-[11px] ml-auto" style={{ color: colors.dim }}>{packets.length}</span>
          </div>
          <div className="flex-1 overflow-y-auto font-mono text-[11px]">
            {/* Header */}
            <div className="flex items-center px-2 py-1 border-b sticky top-0" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel, color: colors.dim }}>
              <span className="w-9 text-right shrink-0">#</span>
              <span className="w-[60px] ml-2 shrink-0">time</span>
              <span className="w-[120px] ml-2 shrink-0">cmd</span>
              <span className="flex-1 ml-2">args</span>
            </div>
            {packets.length === 0 ? (
              <div className="flex items-center justify-center py-8 text-[11px]" style={{ color: colors.dim }}>
                Waiting for imaging packets...
              </div>
            ) : (
              packets.map((p, i) => {
                const isLatest = i === packets.length - 1 && receiving
                return (
                  <div
                    key={i}
                    className="flex items-center px-2 py-0.5 hover:bg-white/[0.02]"
                    style={{
                      color: colors.value,
                      backgroundColor: isLatest ? `${colors.success}0A` : undefined,
                    }}
                  >
                    <span className="w-9 text-right shrink-0" style={{ color: colors.dim }}>{p.num}</span>
                    <span className="w-[60px] ml-2 shrink-0" style={{ color: colors.dim }}>{p.time}</span>
                    <span className="w-[120px] ml-2 shrink-0">{p.cmd}</span>
                    <span className="flex-1 ml-2 truncate">{p.args}</span>
                  </div>
                )
              })
            )}
            <div ref={listEndRef} />
          </div>
        </div>

        {/* TX Controls */}
        <div className="rounded-lg border overflow-hidden" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}>
          <div className="flex items-center gap-2 px-3 py-1.5 border-b" style={{ borderColor: colors.borderSubtle }}>
            <Send className="size-3.5" style={{ color: colors.dim }} />
            <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.label }}>TX Controls</span>
          </div>
          <div className="p-3 space-y-3">
            {/* Destination node */}
            <div>
              <div className="text-[11px] font-medium mb-1" style={{ color: colors.dim }}>Destination</div>
              <div className="flex flex-wrap gap-1">
                {nodes.map(n => (
                  <button
                    key={n}
                    onClick={() => setDestNode(n)}
                    className="px-2 py-0.5 rounded text-[11px] font-medium border"
                    style={{
                      borderColor: destNode === n ? colors.label : colors.borderSubtle,
                      backgroundColor: destNode === n ? `${colors.label}18` : 'transparent',
                      color: destNode === n ? colors.label : colors.dim,
                    }}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>

            {/* Count Chunks */}
            <div>
              <div className="text-[11px] font-medium mb-1" style={{ color: colors.dim }}>Count Chunks</div>
              <div className="flex gap-2">
                <GssInput
                  className="w-full"
                  placeholder="filename"
                  value={cntFilename}
                  onChange={e => setCntFilename(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleCntChunks() }}
                />
                <GssInput
                  className="!w-20"
                  placeholder="chunk size"
                  value={cntChunkSize}
                  onChange={e => setCntChunkSize(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleCntChunks() }}
                />
                <Button size="sm" onClick={handleCntChunks} className="h-7 px-3 text-[11px] shrink-0" style={{ backgroundColor: colors.label, color: colors.bgApp }}>
                  Send
                </Button>
              </div>
            </div>

            {/* Get Chunk */}
            <div>
              <div className="text-[11px] font-medium mb-1" style={{ color: colors.dim }}>Get Chunk</div>
              <div className="flex gap-2">
                <GssInput
                  className="w-full"
                  placeholder="filename"
                  value={getFilename}
                  onChange={e => setGetFilename(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleGetChunk() }}
                />
                <GssInput
                  className="!w-20"
                  placeholder="start #"
                  value={getStartChunk}
                  onChange={e => setGetStartChunk(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleGetChunk() }}
                />
                <GssInput
                  className="!w-20"
                  placeholder="count"
                  value={getNumChunks}
                  onChange={e => setGetNumChunks(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleGetChunk() }}
                />
                <Button size="sm" onClick={handleGetChunk} className="h-7 px-3 text-[11px] shrink-0" style={{ backgroundColor: colors.label, color: colors.bgApp }}>
                  Send
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Right Column ─────────────────────────────────── */}
      <div className="flex-1 flex flex-col gap-4">
        {/* Progress block */}
        <div className="rounded-lg border overflow-hidden shrink-0" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}>
          <div className="flex items-center gap-2 px-3 py-1.5 border-b" style={{ borderColor: colors.borderSubtle }}>
            <Grid3x3 className="size-3.5" style={{ color: colors.dim }} />
            <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.label }}>Progress</span>
            <div className="flex-1" />
            {files.length > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger
                  className="flex items-center gap-1 border rounded px-2 py-0.5 text-[11px] outline-none hover:bg-white/[0.04]"
                  style={{ borderColor: colors.borderSubtle, color: colors.value }}
                >
                  {selectedFile || 'Select file'}
                  {selectedFile && (() => {
                    const f = files.find(f => f.filename === selectedFile)
                    if (!f) return null
                    return <span style={{ color: f.complete ? colors.success : colors.dim }}>{f.complete ? '(complete)' : f.total ? `(${f.received}/${f.total})` : ''}</span>
                  })()}
                  <ChevronDown className="size-3" style={{ color: colors.dim }} />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="min-w-[200px]">
                  {files.map(f => (
                    <DropdownMenuItem
                      key={f.filename}
                      onClick={() => setSelectedFile(f.filename)}
                      className="text-[11px] font-mono flex justify-between gap-4"
                    >
                      <span>{f.filename}</span>
                      <span style={{ color: f.complete ? colors.success : colors.dim }}>
                        {f.complete ? 'complete' : f.total ? `${f.received}/${f.total}` : '...'}
                      </span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
          {prog && prog.total ? (() => {
            const missingChunks = Array.from({ length: prog.total }, (_, i) => i).filter(i => !chunks.includes(i))
            const pct = Math.round((prog.received / prog.total) * 100)
            return (
              <div className="px-3 py-2">
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-[11px] font-medium" style={{ color: colors.value }}>
                    {prog.received} / {prog.total}
                  </span>
                  <span className="text-[11px]" style={{ color: colors.dim }}>({pct}%)</span>
                  <span className="text-[11px] ml-auto" style={{ color: prog.complete ? colors.success : missingChunks.length > 0 ? colors.warning : colors.active }}>
                    {prog.complete ? 'Complete' : missingChunks.length > 0 ? `${missingChunks.length} missing` : 'Receiving...'}
                  </span>
                </div>
                <div className="flex flex-wrap gap-0.5">
                  {Array.from({ length: prog.total }, (_, i) => {
                    const received = chunks.includes(i)
                    return (
                      <div
                        key={i}
                        className="rounded-full"
                        style={{
                          width: 7,
                          height: 7,
                          backgroundColor: received ? colors.success : colors.danger,
                        }}
                        title={`Chunk ${i}${received ? '' : ' (missing)'}`}
                      />
                    )
                  })}
                </div>
                {missingChunks.length > 0 && !prog.complete && (
                  <div className="text-[11px] font-mono mt-1.5 flex flex-wrap gap-x-1.5 gap-y-0.5" style={{ color: colors.dim }}>
                    <span style={{ color: colors.danger }}>Missing:</span>
                    {formatMissingRanges(missingChunks).map((range, i) => (
                      <span key={i} style={{ color: colors.value }}>{range}</span>
                    ))}
                  </div>
                )}
              </div>
            )
          })() : (
            <div className="px-3 py-3 text-[11px]" style={{ color: colors.dim }}>
              {files.length === 0 ? 'No active transfers' : 'Waiting for chunk count...'}
            </div>
          )}
        </div>

        {/* Image preview block */}
        <div className="flex-1 rounded-lg border overflow-hidden flex flex-col" style={{ borderColor: colors.borderSubtle, backgroundColor: colors.bgPanel }}>
          <div className="flex items-center gap-2 px-3 py-1.5 border-b shrink-0" style={{ borderColor: colors.borderSubtle }}>
            <Image className="size-3.5" style={{ color: colors.dim }} />
            <span className="text-[11px] font-bold uppercase tracking-wider" style={{ color: colors.label }}>Preview</span>
            {selectedFile && <span className="text-[11px] font-mono" style={{ color: colors.dim }}>{selectedFile}</span>}
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
              <div className="absolute inset-0 flex items-center justify-center text-[11px]" style={{ color: colors.dim }}>
                {files.length === 0 ? 'No images yet' : 'Select a file to preview'}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
