import { useState, useEffect, useRef } from 'react';
import {
  Send,
  Camera,
  Wrench,
  Download,
  Power,
  PowerOff,
  Image,
  ImageMinus,
} from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { GssInput } from '@/components/ui/gss-input';
import { showToast } from '@/components/shared/StatusToast';
import { colors } from '@/lib/colors';
import { withJpg, DEFAULT_CHUNK_SIZE } from './helpers';
import { FilenameInput } from './FilenameInput';
import type { PairedFile, ImagingTab } from './types';

interface TxControlsPanelProps {
  nodes: string[];
  destNode: string;
  onDestNodeChange: (n: string) => void;
  targetArg: string;
  onTargetChange: (t: string) => void;
  /** Currently-selected paired file (drives auto-fill per active preview tab) */
  selected: PairedFile | null;
  /** Which side the Preview is currently showing — auto-fill source */
  previewTab: ImagingTab;
  /** Stage a command into the main TX queue */
  queueCommand: (cmd: {
    cmd_id: string;
    args: Record<string, string>;
    dest: string;
    echo: string;
    ptype: string;
  }) => void;
  /** Schema for looking up echo/ptype per command */
  schema: Record<string, Record<string, unknown>> | null;
  txConnected: boolean;
}

type TabName = 'download' | 'camera' | 'edit';

export function TxControlsPanel({
  nodes,
  destNode,
  onDestNodeChange,
  targetArg,
  onTargetChange,
  selected,
  previewTab,
  queueCommand,
  schema,
  txConnected,
}: TxControlsPanelProps) {
  const [activeTab, setActiveTab] = useState<TabName>('download');

  // ── Download tab form state + auto-fill ─────────────────────────
  const [cntFn, setCntFn] = useState('');
  const [cntSize, setCntSize] = useState(DEFAULT_CHUNK_SIZE);
  const [getFn, setGetFn] = useState('');
  const [getStart, setGetStart] = useState('');
  const [getCount, setGetCount] = useState('');
  const autoRef = useRef({ cntFn: '', getFn: '', start: '', count: '' });

  // Source filename = whichever leaf matches the Preview's active tab.
  // If one side is null (prefix unset, orphan pair), fall back to the
  // side that exists so auto-fill still works.
  const effectiveLeaf = selected
    ? !selected.thumb
      ? selected.full
      : !selected.full
      ? selected.thumb
      : previewTab === 'thumb'
      ? selected.thumb
      : selected.full
    : null;
  const suggestedFilename = effectiveLeaf?.filename ?? '';
  const suggestedTotal = effectiveLeaf?.total ?? null;

  useEffect(() => {
    if (!suggestedFilename) return;
    const lastCnt = autoRef.current.cntFn;
    const lastGet = autoRef.current.getFn;
    setCntFn(prev => (prev === '' || prev === lastCnt ? suggestedFilename : prev));
    setGetFn(prev => (prev === '' || prev === lastGet ? suggestedFilename : prev));
    autoRef.current.cntFn = suggestedFilename;
    autoRef.current.getFn = suggestedFilename;
  }, [suggestedFilename]);

  useEffect(() => {
    if (!suggestedFilename || suggestedTotal == null || suggestedTotal <= 0) return;
    const lastStart = autoRef.current.start;
    const lastCount = autoRef.current.count;
    setGetStart(prev => (prev === '' || prev === lastStart ? '0' : prev));
    setGetCount(prev => (prev === '' || prev === lastCount ? String(suggestedTotal) : prev));
    autoRef.current.start = '0';
    autoRef.current.count = String(suggestedTotal);
  }, [suggestedFilename, suggestedTotal]);

  // Camera tab
  const [capFn, setCapFn] = useState('');

  // Edit on Pi tab
  const [compFn, setCompFn] = useState('');
  const [compQ, setCompQ] = useState('80');
  const [rszFn, setRszFn] = useState('');
  const [rszW, setRszW] = useState('640');
  const [rszH, setRszH] = useState('480');
  const [thmbFn, setThmbFn] = useState('');
  const [delFp, setDelFp] = useState('');

  // ── Stage helpers ──────────────────────────────────────────────
  const stage = (cmdId: string, args: Record<string, string>) => {
    if (!txConnected) {
      showToast('TX not connected', 'error', 'tx');
      return;
    }
    if (!destNode) {
      showToast('No destination node selected', 'error', 'tx');
      return;
    }
    queueCommand({
      cmd_id: cmdId,
      args,
      dest: destNode,
      echo: (schema?.[cmdId] as Record<string, unknown>)?.echo as string ?? 'NONE',
      ptype: (schema?.[cmdId] as Record<string, unknown>)?.ptype as string ?? 'CMD',
    });
  };

  return (
    <div
      className="rounded-lg border overflow-hidden flex flex-col flex-1 min-h-0"
      style={{
        borderColor: colors.borderSubtle,
        backgroundColor: colors.bgPanel,
        boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
      }}
    >
      {/* Header — title + Route + Target chips */}
      <div
        className="flex items-center gap-2 px-3 py-1.5 border-b flex-wrap"
        style={{ borderColor: colors.borderSubtle }}
      >
        <Send className="size-3.5" style={{ color: colors.dim }} />
        <span
          className="text-[11px] font-bold uppercase tracking-wider"
          style={{ color: colors.value }}
        >
          Imaging TX Controls
        </span>
        <div className="flex-1" />
        <div className="flex items-center gap-1">
          {nodes.map(n => {
            const active = destNode === n;
            return (
              <button
                key={n}
                onClick={() => onDestNodeChange(n)}
                className="px-2 rounded-sm border font-mono text-[11px] color-transition btn-feedback"
                style={{
                  height: 20,
                  color: active ? colors.label : colors.dim,
                  borderColor: active ? colors.label : colors.borderSubtle,
                  backgroundColor: active ? `${colors.label}18` : 'transparent',
                }}
                title={`Route · ${n}`}
              >
                {n}
              </button>
            );
          })}
        </div>
        <div className="w-px h-4 bg-[#222]" />
        <div className="flex items-center gap-1">
          {(['1', '2'] as const).map(t => {
            const active = targetArg === t;
            const label = t === '1' ? '1 · full' : '2 · thumb';
            const Icon = t === '1' ? Image : ImageMinus;
            const title = t === '1' ? 'target 1 — full-size images' : 'target 2 — thumbnails';
            return (
              <button
                key={t}
                onClick={() => onTargetChange(t)}
                className="inline-flex items-center gap-1 px-2 rounded-sm border font-mono text-[11px] color-transition btn-feedback"
                style={{
                  height: 20,
                  color: active ? colors.label : colors.dim,
                  borderColor: active ? colors.label : colors.borderSubtle,
                  backgroundColor: active ? `${colors.label}18` : 'transparent',
                }}
                title={title}
              >
                <Icon className="size-2.5" />
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as TabName)} className="flex-1 flex flex-col min-h-0">
        <TabsList className="h-auto w-full grid grid-cols-3 gap-0 border-b rounded-none p-0" style={{ borderColor: colors.borderSubtle }}>
          <TabsTrigger value="download" className="gap-1.5 text-[10px] py-2 uppercase tracking-wider rounded-none">
            <Download className="size-3" />Download
          </TabsTrigger>
          <TabsTrigger value="camera" className="gap-1.5 text-[10px] py-2 uppercase tracking-wider rounded-none">
            <Camera className="size-3" />Camera Control
          </TabsTrigger>
          <TabsTrigger value="edit" className="gap-1.5 text-[10px] py-2 uppercase tracking-wider rounded-none">
            <Wrench className="size-3" />Image Edit
          </TabsTrigger>
        </TabsList>

        {/* Download */}
        <TabsContent value="download" className="flex-1 overflow-y-auto p-3 space-y-4 mt-0">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: colors.dim }}>
              Count Chunks <span className="font-mono normal-case ml-1" style={{ color: colors.sep }}>img_cnt_chunks</span>
            </div>
            <div className="flex items-end gap-2">
              <FilenameInput className="flex-1" value={cntFn} onChange={setCntFn} />
              <GssInput
                className="w-[70px] font-mono"
                placeholder="chunk size"
                value={cntSize}
                onChange={e => setCntSize(e.target.value)}
              />
              <Button
                size="sm"
                onClick={() =>
                  stage('img_cnt_chunks', {
                    Filename: withJpg(cntFn.trim()),
                    Destination: targetArg,
                    'Chunk Size': cntSize.trim() || DEFAULT_CHUNK_SIZE,
                  })
                }
                style={{ backgroundColor: colors.active, color: colors.bgApp }}
              >
                Stage
              </Button>
            </div>
          </div>

          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: colors.dim }}>
              Get Chunk <span className="font-mono normal-case ml-1" style={{ color: colors.sep }}>img_get_chunk · contiguous range</span>
            </div>
            <div className="flex items-end gap-2">
              <FilenameInput className="flex-1" value={getFn} onChange={setGetFn} />
              <GssInput
                className="w-[52px] font-mono"
                placeholder="start"
                value={getStart}
                onChange={e => setGetStart(e.target.value)}
              />
              <GssInput
                className="w-[52px] font-mono"
                placeholder="count"
                value={getCount}
                onChange={e => setGetCount(e.target.value)}
              />
              <Button
                size="sm"
                disabled={!suggestedTotal}
                title={!suggestedTotal ? 'Run img_cnt_chunks or cam_capture_img first' : undefined}
                onClick={() =>
                  stage('img_get_chunk', {
                    Filename: withJpg(getFn.trim()),
                    'Start Chunk': getStart.trim(),
                    'Num Chunks': getCount.trim(),
                    Destination: targetArg,
                  })
                }
                style={{ backgroundColor: colors.active, color: colors.bgApp }}
              >
                Stage
              </Button>
            </div>
          </div>
        </TabsContent>

        {/* Camera */}
        <TabsContent value="camera" className="flex-1 overflow-y-auto p-3 space-y-3 mt-0">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: colors.dim }}>
              cam_capture_img
            </div>
            <div className="flex items-end gap-2">
              <FilenameInput className="flex-1" value={capFn} onChange={setCapFn} />
              <Button
                size="sm"
                onClick={() => {
                  const fn = capFn.trim();
                  if (!fn) {
                    showToast('Filename required', 'error', 'tx');
                    return;
                  }
                  stage('cam_capture_img', { Filename: withJpg(fn) });
                }}
                style={{ backgroundColor: colors.active, color: colors.bgApp }}
              >
                Stage
              </Button>
            </div>
          </div>

          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: colors.dim }}>
              Power
            </div>
            <div className="flex gap-1.5">
              <Button size="sm" variant="secondary" className="flex-1" onClick={() => stage('cam_on', {})}>
                <Power className="size-3" /> cam_on
              </Button>
              <Button size="sm" variant="secondary" className="flex-1" onClick={() => stage('cam_off', {})}>
                <PowerOff className="size-3" /> cam_off
              </Button>
            </div>
          </div>
        </TabsContent>

        {/* Edit on Pi */}
        <TabsContent value="edit" className="flex-1 overflow-y-auto p-3 space-y-3 mt-0">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: colors.dim }}>
              img_compress
            </div>
            <div className="flex items-end gap-2">
              <FilenameInput className="flex-1" value={compFn} onChange={setCompFn} />
              <GssInput className="w-[60px] font-mono" placeholder="qual" value={compQ} onChange={e => setCompQ(e.target.value)} />
              <Button size="sm" onClick={() => stage('img_compress', { Filename: withJpg(compFn.trim()), Quality: compQ.trim() || '80' })} style={{ backgroundColor: colors.active, color: colors.bgApp }}>
                Stage
              </Button>
            </div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: colors.dim }}>
              img_resize
            </div>
            <div className="flex items-end gap-2">
              <FilenameInput className="flex-1" value={rszFn} onChange={setRszFn} />
              <GssInput className="w-[52px] font-mono" placeholder="W" value={rszW} onChange={e => setRszW(e.target.value)} />
              <GssInput className="w-[52px] font-mono" placeholder="H" value={rszH} onChange={e => setRszH(e.target.value)} />
              <Button size="sm" onClick={() => stage('img_resize', { Filename: withJpg(rszFn.trim()), Width: rszW.trim(), Height: rszH.trim() })} style={{ backgroundColor: colors.active, color: colors.bgApp }}>
                Stage
              </Button>
            </div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: colors.dim }}>
              img_dfl_thumb
            </div>
            <div className="flex items-end gap-2">
              <FilenameInput className="flex-1" value={thmbFn} onChange={setThmbFn} />
              <Button size="sm" onClick={() => stage('img_dfl_thumb', { Filename: withJpg(thmbFn.trim()) })} style={{ backgroundColor: colors.active, color: colors.bgApp }}>
                Stage
              </Button>
            </div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: colors.danger }}>
              img_delete
            </div>
            <div className="flex items-end gap-2">
              <GssInput className="flex-1 font-mono" placeholder="filepath (full path on Pi)" value={delFp} onChange={e => setDelFp(e.target.value)} />
              <Button size="sm" onClick={() => stage('img_delete', { Filepath: delFp.trim() })} style={{ backgroundColor: colors.danger, color: colors.bgApp }}>
                Stage
              </Button>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
