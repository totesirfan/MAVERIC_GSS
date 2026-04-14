import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { showToast } from '@/components/shared/StatusToast'
import { usePluginServices } from '@/hooks/usePluginServices'

import { RxLogPanel, type ImagingLogRow } from './imaging/RxLogPanel'
import { TxControlsPanel, type PendingCmd } from './imaging/TxControlsPanel'
import { ProgressPanel } from './imaging/ProgressPanel'
import { PreviewPanel } from './imaging/PreviewPanel'
import { fetchImagingStatus, type ImagingFileStatus } from './imaging/helpers'

/**
 * MAVERIC imaging plugin page — host for the RX log, TX controls, progress
 * grid, and JPEG preview. This component owns global imaging state (files,
 * selection, chunks) and delegates rendering to the panels under ./imaging/.
 */
export default function ImagingPage() {
  const {
    packets: rxPackets, config, queueCommand, txConnected,
    subscribeRxCustom, sessionResetGen, fetchSchema,
    sendAll, abortSend, sendProgress, guardConfirm, approveGuard, rejectGuard,
  } = usePluginServices()

  // ── Imaging file/chunk state ────────────────────────────────────────
  const [files, setFiles] = useState<ImagingFileStatus[]>([])
  const [selectedFile, setSelectedFile] = useState<string>('')
  const [chunks, setChunks] = useState<number[]>([])

  // ── RX log state (filtered view of shared RX buffer) ────────────────
  const [packets, setPackets] = useState<ImagingLogRow[]>([])
  const [receiving, setReceiving] = useState(false)
  const receivingTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── TX routing + schema ─────────────────────────────────────────────
  const [destNode, setDestNode] = useState('')
  const [nodes, setNodes] = useState<string[]>([])
  const [schema, setSchema] = useState<Record<string, Record<string, unknown>> | null>(null)

  // ── Pending command + delete confirm ─────────────────────────────────
  const [pendingCmd, setPendingCmd] = useState<PendingCmd | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)

  // ── Schema fetch (once) ──────────────────────────────────────────────
  useEffect(() => {
    fetchSchema().then(setSchema).catch(() => {})
  }, [fetchSchema])

  // ── Resolve imaging-capable routing nodes from config + schema ──────
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

  // ── Initial status fetch ────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    fetchImagingStatus().then(f => {
      if (cancelled) return
      setFiles(f)
      if (f.length > 0) setSelectedFile(prev => prev || f[0].filename)
    })
    return () => { cancelled = true }
  }, [])

  // ── Session reset: clear state + refetch — only on ACTUAL changes,
  //    not when we mount with a pre-existing non-zero reset gen ──────
  const mountResetGen = useRef(sessionResetGen)
  useEffect(() => {
    if (sessionResetGen === mountResetGen.current) return
    let cancelled = false
    setPackets([])
    setReceiving(false)
    setFiles([])
    setSelectedFile('')
    setChunks([])
    fetchImagingStatus().then(f => {
      if (cancelled) return
      setFiles(f)
      if (f.length > 0) setSelectedFile(f[0].filename)
    })
    return () => { cancelled = true }
  }, [sessionResetGen])

  // ── Clean up the receiving-badge timeout on unmount ─────────────────
  useEffect(() => {
    return () => {
      if (receivingTimer.current) clearTimeout(receivingTimer.current)
    }
  }, [])

  // ── Live imaging_progress broadcasts from the adapter ───────────────
  useEffect(() => {
    return subscribeRxCustom((msg) => {
      if (msg.type !== 'imaging_progress') return
      const p = msg as unknown as ImagingFileStatus
      setFiles(prev => {
        const existing = prev.find(f => f.filename === p.filename)
        if (existing) {
          return prev.map(f => f.filename === p.filename
            ? { ...f, received: p.received, total: p.total, complete: p.complete }
            : f)
        }
        return [...prev, p]
      })
      setSelectedFile(p.filename)
    })
  }, [subscribeRxCustom])

  // ── Derive imaging-only RX log rows from shared RX buffer ───────────
  const imagingPackets = useMemo<ImagingLogRow[]>(() => {
    const rows: ImagingLogRow[] = []
    for (const p of rxPackets) {
      const cmdRaw = String(p._rendering?.row?.values?.cmd ?? '')
      if (!cmdRaw.startsWith('img_cnt_chunks') && !cmdRaw.startsWith('img_get_chunk')) continue
      const parts = cmdRaw.split(' ')
      rows.push({
        num: p.num,
        time: p.time,
        cmd: parts[0] ?? '',
        args: parts.slice(1).join(' '),
      })
    }
    return rows
  }, [rxPackets])

  // Mirror new imaging rows into local state and pulse "receiving" badge
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

  // ── Fetch chunk list for the selected file on progress changes ──────
  const selectedProgress = useMemo(
    () => files.find(f => f.filename === selectedFile),
    [files, selectedFile],
  )

  useEffect(() => {
    if (!selectedFile) { setChunks([]); return }
    const ctrl = new AbortController()
    fetch(`/api/plugins/imaging/chunks/${encodeURIComponent(selectedFile)}`, { signal: ctrl.signal })
      .then(r => r.json())
      .then(data => setChunks(data.chunks ?? []))
      .catch(err => { if (err?.name !== 'AbortError') setChunks([]) })
    return () => ctrl.abort()
  }, [selectedFile, selectedProgress?.received])

  // ── Preview version — bump on every chunk arrival so the preview
  //    builds progressively as the image assembles ─────────────────────
  const [previewVersion, setPreviewVersion] = useState(0)
  useEffect(() => {
    if (!selectedFile) return
    setPreviewVersion(v => v + 1)
  }, [selectedFile, selectedProgress?.received, selectedProgress?.complete])

  // ── Command staging: stash (args + destNode snapshot) and wait for Confirm ──
  const stageCommand = useCallback((cmdId: string, args: Record<string, string>, label: string) => {
    if (!txConnected) { showToast('TX not connected', 'error', 'tx'); return }
    if (!destNode) { showToast('No destination node selected', 'error', 'tx'); return }
    // Snapshot destNode at stage time — confirming later uses THIS value,
    // not whatever the operator has since clicked.
    setPendingCmd({ cmdId, args, label, destNode })
  }, [destNode, txConnected])

  const confirmSend = useCallback(() => {
    if (!pendingCmd) return
    queueCommand({
      cmd_id: pendingCmd.cmdId,
      args: pendingCmd.args,
      dest: pendingCmd.destNode,
      echo: (schema?.[pendingCmd.cmdId] as Record<string, unknown>)?.echo as string ?? 'NONE',
      ptype: (schema?.[pendingCmd.cmdId] as Record<string, unknown>)?.ptype as string ?? 'CMD',
    })
    sendAll()
    setPendingCmd(null)
  }, [pendingCmd, queueCommand, schema, sendAll])

  const cancelPending = useCallback(() => setPendingCmd(null), [])

  // ── Delete with proper HTTP error checking ──────────────────────────
  const performDelete = useCallback((filename: string) => {
    fetch(`/api/plugins/imaging/file/${encodeURIComponent(filename)}`, { method: 'DELETE' })
      .then(async r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const body = await r.json().catch(() => ({}))
        if (body && body.ok === false) throw new Error(body.error ?? 'delete failed')
        return body
      })
      .then(() => {
        setFiles(prev => prev.filter(f => f.filename !== filename))
        setSelectedFile(prev => (prev === filename ? '' : prev))
        showToast(`Deleted ${filename}`, 'success', 'tx')
      })
      .catch((err) => {
        showToast(`Failed to delete ${filename}: ${String(err?.message ?? err)}`, 'error', 'tx')
      })
  }, [])

  const handleDelete = useCallback((filename: string) => setDeleteTarget(filename), [])

  return (
    <div className="flex-1 flex overflow-hidden p-4 gap-4">
      {/* ── Left column — RX log + TX controls ─────────────────── */}
      <div className="flex flex-col gap-4 shrink-0" style={{ width: 520 }}>
        <RxLogPanel packets={packets} receiving={receiving} />
        <TxControlsPanel
          nodes={nodes}
          destNode={destNode}
          onDestNodeChange={setDestNode}
          suggestedFilename={selectedFile}
          suggestedTotal={selectedProgress?.total ?? null}
          stageCommand={stageCommand}
          pendingCmd={pendingCmd}
          onConfirmSend={confirmSend}
          onCancelPending={cancelPending}
          sendProgress={sendProgress}
          onAbort={abortSend}
          guardConfirm={guardConfirm}
          onApproveGuard={approveGuard}
          onRejectGuard={rejectGuard}
        />
      </div>

      {/* ── Right column — progress + preview ──────────────────── */}
      <div className="flex-1 flex flex-col gap-4">
        <ProgressPanel
          files={files}
          selectedFile={selectedFile}
          selectedProgress={selectedProgress}
          chunks={chunks}
          onSelect={setSelectedFile}
          onDelete={handleDelete}
        />
        <PreviewPanel
          selectedFile={selectedFile}
          version={previewVersion}
          hasFiles={files.length > 0}
        />
      </div>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete image?"
        detail={deleteTarget
          ? `${deleteTarget} and all its chunks will be removed from disk. This cannot be undone.`
          : undefined}
        variant="destructive"
        onConfirm={() => { if (deleteTarget) performDelete(deleteTarget); setDeleteTarget(null) }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
