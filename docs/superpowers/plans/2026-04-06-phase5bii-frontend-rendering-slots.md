# Phase 5b-ii: Frontend Rendering Slots

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the React frontend's RX packet list, packet row, and packet detail components to render from adapter-provided `_rendering` data and `columns` definitions instead of hardcoded MAVERIC field access.

**Architecture:** The backend already serves `columns` on WebSocket connect and `_rendering` per packet (Phase 5b-i). This phase makes the frontend consume that data. Column headers render dynamically from the `columns` message. PacketRow renders cell values from `_rendering.row`. PacketDetail renders from `_rendering.detail_blocks`, `protocol_blocks`, and `integrity_blocks`. Flat MAVERIC fields remain on the packet JSON for stats computation, filtering, copy/text export, and TX-side components — those are not changed in this phase.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Virtuoso, shadcn/ui

---

## Design Decisions

1. **Flat MAVERIC fields remain on `RxPacket`.** They are still used by `useRxSocket` (stats), `RxPanel` (filtering, text export, copy), and TX components. Removing them is a future cleanup after stats/filtering also go through the adapter.

2. **`_rendering` is an additive overlay.** `RxPacket` gains an optional `_rendering` property. Components that render packet content (list headers, row cells, detail view) read from `_rendering`. Components that compute or filter (stats, uplink hide, copy) continue using flat fields.

3. **Column metadata drives rendering behavior.** The `columns` array includes hints like `badge: true`, `toggle: "showFrame"`, `align: "right"`, `flex: true`, `width: "w-[84px]"`. The platform components interpret these hints — missions provide data, not UI code.

4. **`columns.ts` is kept.** It provides TX-side column widths (`grip`, `actions`) that are not part of the RX rendering contract. The RX-specific widths (`col.node`, `col.ptype`, etc.) will no longer be used by PacketList/PacketRow since they come from `columns` data.

5. **Platform-owned rendering:** Warnings, raw/hex, protocol blocks, and integrity blocks are rendered by fixed platform components. The mission provides the data; the platform decides layout, icons, and styling.

## File Plan

| Action | File | Change |
|---|---|---|
| Modify | `mav_gss_lib/missions/maveric/adapter.py` | Restructure `packet_list_row` return to `{values: {...}, _meta: {...}}` |
| Modify | `mav_gss_lib/web/src/lib/types.ts` | Add `ColumnDef`, `RenderingRow`, `RenderingData` types; add `_rendering?` to `RxPacket` |
| Modify | `mav_gss_lib/web/src/hooks/useRxSocket.ts` | Handle `columns` message; expose `columns` state |
| Modify | `mav_gss_lib/web/src/components/rx/PacketList.tsx` | Render column headers from `columns` prop |
| Modify | `mav_gss_lib/web/src/components/rx/PacketRow.tsx` | Render cell values from `_rendering.row` |
| Modify | `mav_gss_lib/web/src/components/rx/PacketDetail.tsx` | Render from `_rendering` blocks |
| Modify | `mav_gss_lib/web/src/components/rx/RxPanel.tsx` | Pass `columns` to PacketList |
| Modify | `mav_gss_lib/web/src/App.tsx` | Destructure `columns` from `useRxSocket`, pass to `RxPanel` |

## Build Command

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
npm run build
```

Must complete with zero TypeScript errors after each task.

---

## Task 0: Restructure Backend Row Shape

**Files:**
- Modify: `mav_gss_lib/missions/maveric/adapter.py`

The backend `packet_list_row` currently returns a flat dict with `_meta` mixed into column values. The frontend needs a clean separation: `{values: {...column data...}, _meta: {...presentation hints...}}`.

- [ ] **Step 1: Restructure packet_list_row return value**

In `mav_gss_lib/missions/maveric/adapter.py`, find the `packet_list_row` method and wrap the column values under a `values` key, with `_meta` separate:

Change the return from:
```python
        return {
            "num": ...,
            "time": ...,
            ...
            "_meta": {"opacity": 0.5 if pkt.is_unknown else 1.0},
        }
```

To:
```python
        return {
            "values": {
                "num": pkt.pkt_num,
                "time": pkt.gs_ts_short,
                "frame": pkt.frame_type,
                "src": node_name(cmd["src"]) if cmd else "",
                "echo": node_name(cmd["echo"]) if cmd else "",
                "ptype": ptype_name(cmd["pkt_type"]) if cmd else "",
                "cmd": ((cmd["cmd_id"] + " " + args_str).strip() if args_str else cmd["cmd_id"]) if cmd else "",
                "flags": flags,
                "size": len(pkt.raw),
            },
            "_meta": {"opacity": 0.5 if pkt.is_unknown else 1.0},
        }
```

- [ ] **Step 2: Run Python tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -q
```

- [ ] **Step 3: Commit**

```bash
git add mav_gss_lib/missions/maveric/adapter.py
git commit -m "Restructure packet_list_row to separate values from _meta"
```

---

## Task 1: Add Rendering Types

**Files:**
- Modify: `mav_gss_lib/web/src/lib/types.ts`

- [ ] **Step 1: Add rendering contract types**

Add these types after the `RxPacket` interface:

```typescript
// ---- Rendering Slots (architecture spec §4) ----

export interface ColumnDef {
  id: string
  label: string
  width?: string      // Tailwind width class, e.g. "w-[84px]"
  align?: 'left' | 'right'
  flex?: boolean       // true = flex-1, takes remaining space
  badge?: boolean      // true = render value as PtypeBadge
  toggle?: string      // toggle name that controls visibility, e.g. "showFrame"
}

export interface RenderingFlag {
  tag: string          // e.g. "CRC", "UL", "DUP", "UNK"
  tone: string         // e.g. "danger", "warning", "info"
}

export interface RenderingMeta {
  opacity?: number
}

/** Column values keyed by column ID, plus optional presentation metadata. */
export interface RenderingRow {
  /** Column values — keys match ColumnDef.id */
  values: Record<string, string | number | RenderingFlag[]>
  /** Optional presentation metadata (opacity, etc.) */
  _meta?: RenderingMeta
}

export interface BlockField {
  name: string
  value: string
}

export interface DetailBlock {
  kind: string
  label: string
  fields: BlockField[]
}

export interface IntegrityBlock {
  kind: string
  label: string
  scope: string
  ok: boolean | null
  received?: string | null
  computed?: string | null
}

export interface RenderingData {
  row: RenderingRow
  detail_blocks: DetailBlock[]
  protocol_blocks: DetailBlock[]
  integrity_blocks: IntegrityBlock[]
}
```

- [ ] **Step 2: Add `_rendering` to RxPacket**

Add this optional property at the end of the `RxPacket` interface (before the closing `}`):

```typescript
  // Rendering-slot data (Phase 5b-i backend)
  _rendering?: RenderingData
```

- [ ] **Step 3: Build to verify types**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
npm run build
```

Expected: Build succeeds. Existing components don't use `_rendering` yet, so no breakage.

- [ ] **Step 4: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add mav_gss_lib/web/src/lib/types.ts
git commit -m "Add rendering-slot TypeScript types for adapter-driven UI"
```

---

## Task 2: Handle Columns in useRxSocket

**Files:**
- Modify: `mav_gss_lib/web/src/hooks/useRxSocket.ts`

- [ ] **Step 1: Add columns state and handler**

Import `ColumnDef` at the top:

```typescript
import type { ColumnDef, RxPacket, RxStatus } from '@/lib/types'
```

Add state for columns inside `useRxSocket()`, after the existing state declarations:

```typescript
  const [columns, setColumns] = useState<ColumnDef[]>([])
```

In the WebSocket message handler (the `(data) => {` callback), add a handler for the `columns` message BEFORE the existing `packet` handler:

```typescript
        if (msg.type === 'columns' && msg.data) {
          setColumns(msg.data as ColumnDef[])
        } else if (msg.type === 'packet' && msg.data) {
```

Update the return value to include `columns`:

```typescript
  return { packets, status, connected, stats, columns, clearPackets, replayMode, replacePackets, enterReplay, exitReplay }
```

- [ ] **Step 2: Build**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
npm run build
```

Expected: Build succeeds. The `columns` value is now available but not consumed yet.

- [ ] **Step 3: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add mav_gss_lib/web/src/hooks/useRxSocket.ts
git commit -m "Handle columns WebSocket message in useRxSocket"
```

---

## Task 3: Dynamic Column Headers in PacketList

**Files:**
- Modify: `mav_gss_lib/web/src/components/rx/PacketList.tsx`

- [ ] **Step 1: Add columns prop**

Import `ColumnDef`:

```typescript
import type { ColumnDef, GssConfig, RxPacket } from '@/lib/types'
```

Add `columns` to `PacketListProps`:

```typescript
  columns: ColumnDef[]
```

- [ ] **Step 2: Replace hardcoded column headers**

Replace the hardcoded header row (lines 120–131, the `<div className="flex items-center text-[11px]...">` block) with a dynamic renderer:

```tsx
      {filtered.length > 0 && (
        <div className="flex items-center text-[11px] font-light px-2 py-0.5 shrink-0" style={{ color: colors.sep }}>
          <span className="w-5 px-1" />
          {(columns ?? []).length > 0 ? (
            // Dynamic columns from adapter
            columns!.map(c => {
              if (c.toggle === 'showFrame' && !showFrame) return null
              if (c.toggle === 'showEcho' && !showEcho) return null
              return (
                <span
                  key={c.id}
                  className={`px-2 shrink-0 ${c.flex ? 'flex-1' : ''} ${c.align === 'right' ? 'text-right' : ''} ${c.width ?? ''}`}
                >
                  {c.label}
                </span>
              )
            })
          ) : (
            // Fallback: hardcoded MAVERIC headers (replay / missing columns)
            <>
              <span className="w-10 px-2 text-right">#</span>
              <span className="w-[72px] px-2">time</span>
              {showFrame && <span className="w-[76px] px-2">frame</span>}
              <span className="w-[84px] px-2">src</span>
              {showEcho && <span className="w-[84px] px-2">echo</span>}
              <span className="w-[52px] px-1">type</span>
              <span className="flex-1 px-2">cmd / args</span>
              <span className="w-[76px] px-2 text-right"></span>
              <span className="w-12 px-2 text-right">size</span>
            </>
          )}
        </div>
      )}
```

Remove the `col` import from `@/lib/columns` — it's no longer used in this file.

- [ ] **Step 3: Pass columns through to the component**

In `RxPanel.tsx`, the `PacketList` call needs `columns` added. This will be done in Task 6. For now, the TypeScript build will error because `columns` is required but not passed. To keep the build passing at this step, make the `columns` prop optional with a default:

```typescript
  columns?: ColumnDef[]
```

The Step 2 code already handles the optional case with a ternary (dynamic columns vs hardcoded fallback). No additional guard change needed.

- [ ] **Step 4: Build**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
npm run build
```

- [ ] **Step 5: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add mav_gss_lib/web/src/components/rx/PacketList.tsx
git commit -m "Render packet list column headers from adapter-provided columns"
```

---

## Task 4: Dynamic Row Cells in PacketRow

**Files:**
- Modify: `mav_gss_lib/web/src/components/rx/PacketRow.tsx`

- [ ] **Step 1: Add columns prop and rendering imports**

Import types:

```typescript
import type { ColumnDef, GssConfig, RenderingFlag, RxPacket } from '@/lib/types'
```

Add to `PacketRowProps`:

```typescript
  columns?: ColumnDef[]
```

- [ ] **Step 2: Add a generic cell renderer**

Add this function inside `PacketRow.tsx`, before the `PacketRow` component:

```tsx
function CellValue({ col: c, row, showFrame, showEcho, nodeDescriptions }: {
  col: ColumnDef
  row: { values: Record<string, unknown>; _meta?: { opacity?: number } }
  showFrame: boolean
  showEcho: boolean
  nodeDescriptions?: GssConfig['node_descriptions']
}) {
  // Toggle visibility
  if (c.toggle === 'showFrame' && !showFrame) return null
  if (c.toggle === 'showEcho' && !showEcho) return null

  const val = row.values[c.id]
  const width = c.flex ? 'flex-1 min-w-0 truncate' : `${c.width ?? ''} shrink-0`
  const align = c.align === 'right' ? 'text-right' : ''

  // Badge column (ptype)
  if (c.badge) {
    return (
      <span className={`py-1.5 px-1 ${width}`}>
        <PtypeBadge ptype={val as string | number} />
      </span>
    )
  }

  // Flags column
  if (c.id === 'flags' && Array.isArray(val)) {
    const flags = val as RenderingFlag[]
    return (
      <span className={`py-1.5 px-2 ${width} ${align}`}>
        <span className="flex items-center gap-1 justify-end whitespace-nowrap">
          {flags.map((f, i) => (
            <Badge key={i} variant={f.tone === 'danger' ? 'destructive' : 'secondary'} className="text-[11px] px-1 py-0 h-5"
              style={f.tone !== 'danger' ? { backgroundColor: `${f.tone === 'warning' ? colors.warning : colors.ulColor}22`, color: f.tone === 'warning' ? colors.warning : colors.ulColor } : undefined}>
              {f.tag}
            </Badge>
          ))}
        </span>
      </span>
    )
  }

  // Node columns (src, echo) — with tooltip
  if (c.id === 'src' || c.id === 'echo') {
    const nodeColor = c.id === 'echo' ? colors.warning : colors.label
    return (
      <span className={`py-1.5 px-2 ${width} whitespace-nowrap`}>
        <NodeName name={String(val ?? '')} color={nodeColor} nodeDescriptions={nodeDescriptions} />
      </span>
    )
  }

  // Cmd column — display-ready string from backend, no re-parsing
  if (c.id === 'cmd') {
    return (
      <span className={`py-1.5 px-2 ${width}`} style={{ color: colors.value }}>
        {String(val ?? '') || '--'}
      </span>
    )
  }

  // Frame column — with color
  if (c.id === 'frame') {
    return (
      <span className={`py-1.5 px-2 ${width} whitespace-nowrap`} style={{ color: frameColor(String(val ?? '')) }}>
        {String(val ?? '')}
      </span>
    )
  }

  // Num column
  if (c.id === 'num') {
    return <span className={`py-1.5 px-2 ${width} tabular-nums ${align}`}>{val}</span>
  }

  // Default text cell
  return (
    <span className={`py-1.5 px-2 ${width} ${align} whitespace-nowrap`} style={{ color: colors.dim }}>
      {c.id === 'size' ? `${val}B` : String(val ?? '')}
    </span>
  )
}
```

- [ ] **Step 3: Replace the hardcoded row body**

Replace the contents of the `<div onClick={onClick} className="flex items-center...">` (the main row div) with a dynamic renderer that uses `_rendering.row` when available, falling back to flat fields:

```tsx
          {/* Expand indicator */}
          <span className="py-1.5 px-1 w-5 shrink-0 flex items-center justify-center">
            <ChevronRight
              className="size-3 transition-transform duration-200 ease-out"
              style={{ color: selected ? colors.label : colors.textDisabled, transform: selected ? 'rotate(90deg)' : 'rotate(0deg)' }}
            />
          </span>
          {(columns ?? []).length > 0 && p._rendering?.row ? (
            // Dynamic rendering from adapter-provided row data
            <>
              {columns!.map(c => (
                <CellValue key={c.id} col={c} row={p._rendering!.row}
                  showFrame={showFrame} showEcho={showEcho} nodeDescriptions={nodeDescriptions} />
              ))}
            </>
          ) : (
            // Fallback: hardcoded MAVERIC fields (backward compat)
            <>
              <span className={`py-1.5 px-2 w-10 shrink-0 text-right tabular-nums`} style={{ color: selected ? colors.label : colors.dim }}>{p.num}</span>
              <span className={`py-1.5 px-2 w-[72px] shrink-0 tabular-nums whitespace-nowrap`} style={{ color: colors.dim }}>{p.time}</span>
              {showFrame && <span className={`py-1.5 px-2 w-[76px] shrink-0 whitespace-nowrap`} style={{ color: frameColor(p.frame) }}>{p.frame}</span>}
              <span className={`py-1.5 px-2 w-[84px] shrink-0 whitespace-nowrap`}><NodeName name={p.src} color={colors.label} nodeDescriptions={nodeDescriptions} /></span>
              {showEcho && <span className={`py-1.5 px-2 w-[84px] shrink-0 whitespace-nowrap`}><NodeName name={p.echo} color={colors.warning} nodeDescriptions={nodeDescriptions} /></span>}
              <span className={`py-1.5 px-1 w-[52px] shrink-0`}><PtypeBadge ptype={p.ptype} /></span>
              <span className="py-1.5 px-2 flex-1 min-w-0 truncate">
                <span className="inline-block px-1.5 py-0 rounded-sm text-[11px] font-semibold" style={{ color: colors.value, backgroundColor: 'rgba(255,255,255,0.06)' }}>{p.cmd || '--'}</span>
                {importantArgs(p) && <span className="ml-2" style={{ color: colors.dim }}>{importantArgs(p)}</span>}
              </span>
              <span className={`py-1.5 px-2 w-[76px] shrink-0`}>
                <span className="flex items-center gap-1 justify-end whitespace-nowrap">
                  {p.crc16_ok === false && <Badge variant="destructive" className="text-[11px] px-1 py-0 h-5">CRC</Badge>}
                  {p.is_echo && <Badge className="text-[11px] px-1 py-0 h-5" style={{ backgroundColor: `${colors.ulColor}22`, color: colors.ulColor }}>UL</Badge>}
                  {p.is_dup && <Badge className="text-[11px] px-1 py-0 h-5" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>DUP</Badge>}
                  {p.is_unknown && <Badge className="text-[11px] px-1 py-0 h-5" style={{ backgroundColor: `${colors.error}22`, color: colors.error }}>UNK</Badge>}
                </span>
              </span>
              <span className={`py-1.5 px-2 w-12 shrink-0 text-right tabular-nums whitespace-nowrap`} style={{ color: colors.dim }}>{p.size}B</span>
            </>
          )}
```

Update the row's opacity to use `_rendering.row._meta.opacity` when available:

```tsx
          style={{
            opacity: p._rendering?.row?._meta?.opacity
              ?? (p.is_unknown ? 0.5 : (p.ptype === 'NONE' || p.ptype === '0') ? 0.4 : 1),
          }}
```

- [ ] **Step 4: Build**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
npm run build
```

- [ ] **Step 5: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add mav_gss_lib/web/src/components/rx/PacketRow.tsx
git commit -m "Render packet row cells from adapter-provided _rendering.row"
```

---

## Task 5: Dynamic PacketDetail

**Files:**
- Modify: `mav_gss_lib/web/src/components/rx/PacketDetail.tsx`

- [ ] **Step 1: Import rendering types**

```typescript
import type { DetailBlock, GssConfig, IntegrityBlock as IntegrityBlockType, RxPacket } from '@/lib/types'
```

- [ ] **Step 2: Add generic block renderers**

Add these components before the main `PacketDetail` export:

```tsx
function SemanticBlocks({ blocks }: { blocks: DetailBlock[] }) {
  return (
    <>
      {blocks.map((block, bi) => (
        <div key={bi} className={block.kind === 'args' ? 'space-y-0.5' : 'flex items-center gap-4'}>
          {block.fields.map((f, fi) => (
            block.kind === 'args' ? (
              <div key={fi} className="flex items-center gap-2 text-xs pl-4">
                <span style={{ color: colors.label }}>{f.name}</span>
                <span style={{ color: colors.sep }}>=</span>
                <span style={{ color: colors.value }}>{f.value}</span>
              </div>
            ) : (
              <F key={fi} label={f.name} value={f.value} color={colors.label} />
            )
          ))}
        </div>
      ))}
    </>
  )
}

function ProtocolBlocks({ blocks }: { blocks: DetailBlock[] }) {
  return (
    <>
      {blocks.map((block, bi) => (
        <div key={bi} className="text-xs whitespace-nowrap overflow-x-auto">
          <span className="font-medium mr-2" style={{ color: colors.sep }}>{block.label}</span>
          {block.fields.map((f, fi) => (
            <span key={fi} className="mr-3">
              <span style={{ color: colors.dim }}>{f.name}=</span>
              <span style={{ color: colors.value }}>{f.value}</span>
            </span>
          ))}
        </div>
      ))}
    </>
  )
}

function IntegrityBlocks({ blocks }: { blocks: IntegrityBlockType[] }) {
  return (
    <div className="flex items-center gap-2">
      <Shield className="size-3" style={{ color: colors.sep }} />
      {blocks.length === 0 ? (
        <span className="text-[11px]" style={{ color: colors.dim }}>No CRC data</span>
      ) : (
        blocks.map((b, i) => (
          <Badge key={i} variant={b.ok === false ? 'destructive' : 'secondary'} className="text-[11px] h-5">
            {b.label}: {b.ok === null ? '?' : b.ok ? 'OK' : 'FAIL'}
          </Badge>
        ))
      )}
    </div>
  )
}
```

- [ ] **Step 3: Use rendering blocks when available**

In the `PacketDetail` component body, replace the content of the outer div with a conditional that uses `_rendering` when available, falling back to the existing hardcoded rendering:

```tsx
  const r = p._rendering

  return (
    <div className="px-3 py-2 space-y-1.5 border-t font-mono" style={{ borderColor: colors.borderSubtle }}>
      {r ? (
        <>
          {/* Mission-provided semantic blocks */}
          <SemanticBlocks blocks={r.detail_blocks} />

          {/* Warnings (platform-owned) */}
          {p.warnings.length > 0 && (
            <div className="flex items-center gap-1">
              <AlertTriangle className="size-3 shrink-0" style={{ color: colors.warning }} />
              {p.warnings.map((w, i) => (
                <Badge key={i} className="text-[11px] h-5" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>
                  {w}
                </Badge>
              ))}
            </div>
          )}

          {/* Protocol + Integrity (platform-owned rendering, mission-provided data) */}
          {showWrapper && (
            <>
              <Separator style={{ backgroundColor: colors.borderSubtle }} />
              <IntegrityBlocks blocks={r.integrity_blocks} />
              <ProtocolBlocks blocks={r.protocol_blocks} />
            </>
          )}

          {/* Raw hex (platform-owned) */}
          {showHex && p.raw_hex && (
            <>
              <Separator style={{ backgroundColor: colors.borderSubtle }} />
              <div className="flex items-start gap-1">
                <Binary className="size-3 mt-0.5 shrink-0" style={{ color: colors.sep }} />
                <pre className="text-[11px] p-2 rounded font-mono flex-1 whitespace-pre-wrap break-all" style={{ color: colors.dim, backgroundColor: colors.bgApp }}>
                  {p.raw_hex.match(/.{1,2}/g)?.join(' ')}
                </pre>
              </div>
            </>
          )}
        </>
      ) : (
        /* Fallback: existing hardcoded MAVERIC rendering */
        <>
          {/* Time */}
          <div className="flex items-center gap-4">
            {p.sat_time_utc ? (
              <F icon={Satellite} label="SAT TIME" value={`${p.sat_time_utc} · ${p.sat_time_local || ''}`} color={colors.value} />
            ) : (
              <F icon={Clock} label="Time" value={p.time} />
            )}
          </div>
          {showFrame && (
            <div className="flex items-center gap-4">
              <F icon={Radio} label="Frame" value={p.frame || '--'} color={frameColor(p.frame)} />
            </div>
          )}
          <div className="flex items-center gap-4">
            <F label="Src" value={p.src} color={colors.label} tooltip={getNodeFullName(p.src, nodeDescriptions)} />
            <F label="Dest" value={p.dest} color={colors.label} tooltip={getNodeFullName(p.dest, nodeDescriptions)} />
            {hasEcho(p.echo) && <F label="Echo" value={p.echo} color={colors.warning} tooltip={getNodeFullName(p.echo, nodeDescriptions)} />}
            <F label="Type" value={p.ptype} color={ptypeColor(p.ptype)} />
          </div>
          <div className="flex items-center gap-4">
            <F icon={ArrowRightLeft} label="Cmd" value={p.cmd || '--'} color={colors.value} />
          </div>
          {(namedArgs.length > 0 || extraArgs.length > 0) && (
            <div className="space-y-0.5">
              {namedArgs.map((a, i) => (
                <div key={i} className="flex items-center gap-2 text-xs pl-4">
                  <span style={{ color: colors.label }}>{a.name}</span>
                  <span style={{ color: colors.sep }}>=</span>
                  <span style={{ color: colors.value }}>{a.value}</span>
                </div>
              ))}
              {extraArgs.map((val, i) => (
                <div key={`extra-${i}`} className="flex items-center gap-2 text-xs pl-4">
                  <span style={{ color: colors.dim }}>arg{namedArgs.length + i}</span>
                  <span style={{ color: colors.sep }}>=</span>
                  <span style={{ color: colors.value }}>{val}</span>
                </div>
              ))}
            </div>
          )}
          {p.warnings.length > 0 && (
            <div className="flex items-center gap-1">
              <AlertTriangle className="size-3 shrink-0" style={{ color: colors.warning }} />
              {p.warnings.map((w, i) => (
                <Badge key={i} className="text-[11px] h-5" style={{ backgroundColor: `${colors.warning}22`, color: colors.warning }}>
                  {w}
                </Badge>
              ))}
            </div>
          )}
          {showWrapper && (
            <>
              <Separator style={{ backgroundColor: colors.borderSubtle }} />
              <div className="flex items-center gap-2">
                <Shield className="size-3" style={{ color: colors.sep }} />
                {crc16 !== null && (
                  <Badge variant={crc16 ? 'secondary' : 'destructive'} className="text-[11px] h-5">
                    CRC-16: {crc16 ? 'OK' : 'FAIL'}
                  </Badge>
                )}
                {crc32 !== null && (
                  <Badge variant={crc32 ? 'secondary' : 'destructive'} className="text-[11px] h-5">
                    CRC-32: {crc32 ? 'OK' : 'FAIL'}
                  </Badge>
                )}
                {crc16 === null && crc32 === null && (
                  <span className="text-[11px]" style={{ color: colors.dim }}>No CRC data</span>
                )}
              </div>
              {p.csp_header && (
                <div className="text-xs whitespace-nowrap overflow-x-auto">
                  <span className="font-medium mr-2" style={{ color: colors.sep }}>CSP</span>
                  {Object.entries(p.csp_header).map(([k, v]) => (
                    <span key={k} className="mr-3">
                      <span style={{ color: colors.dim }}>{k}=</span>
                      <span style={{ color: colors.value }}>{v}</span>
                    </span>
                  ))}
                </div>
              )}
              {p.ax25_header && (
                <div className="text-xs">
                  <span className="font-medium mr-2" style={{ color: colors.sep }}>AX.25</span>
                  <span style={{ color: colors.dim }}>{p.ax25_header}</span>
                </div>
              )}
            </>
          )}
          {showHex && p.raw_hex && (
            <>
              <Separator style={{ backgroundColor: colors.borderSubtle }} />
              <div className="flex items-start gap-1">
                <Binary className="size-3 mt-0.5 shrink-0" style={{ color: colors.sep }} />
                <pre className="text-[11px] p-2 rounded font-mono flex-1 whitespace-pre-wrap break-all" style={{ color: colors.dim, backgroundColor: colors.bgApp }}>
                  {p.raw_hex.match(/.{1,2}/g)?.join(' ')}
                </pre>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
```

- [ ] **Step 4: Build**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
npm run build
```

- [ ] **Step 5: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add mav_gss_lib/web/src/components/rx/PacketDetail.tsx
git commit -m "Render packet detail from adapter-provided rendering blocks"
```

---

## Task 6: Wire Columns Through RxPanel

**Files:**
- Modify: `mav_gss_lib/web/src/components/rx/RxPanel.tsx`
- Modify: `mav_gss_lib/web/src/App.tsx` (pass columns from useRxSocket to RxPanel)

- [ ] **Step 1: Add columns prop to RxPanel**

Import `ColumnDef`:

```typescript
import type { ColumnDef, GssConfig, RxPacket, RxStatus } from '@/lib/types'
```

Add to `RxPanelProps`:

```typescript
  columns?: ColumnDef[]
```

Pass `columns` to `PacketList`:

```tsx
        <PacketList
          packets={filtered}
          columns={columns}
          nodeDescriptions={nodeDescriptions}
          ...
```

Pass `columns` to `PacketRow` via `PacketList` — PacketList already passes all props to PacketRow in the `itemContent` callback. Read `PacketList.tsx` to verify PacketRow receives columns. If PacketList doesn't pass columns to PacketRow, add it.

- [ ] **Step 2: Wire columns from App.tsx**

Read `App.tsx` to find where `useRxSocket()` is called and where `RxPanel` is rendered. Destructure `columns` from `useRxSocket()` and pass it to `RxPanel`:

```typescript
const { packets, status, connected, stats, columns, ... } = useRxSocket()
```

```tsx
<RxPanel columns={columns} ... />
```

- [ ] **Step 3: Pass columns from PacketList to PacketRow**

In `PacketList.tsx`, add `columns` to the `PacketRow` props in the `itemContent` callback:

```tsx
                  <PacketRow
                    packet={pkt}
                    columns={columns}
                    nodeDescriptions={nodeDescriptions}
                    ...
```

- [ ] **Step 4: Build**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
npm run build
```

Expected: Build succeeds with zero TypeScript errors.

- [ ] **Step 5: Run Python tests to confirm backend unchanged**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -q

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add mav_gss_lib/web/src/components/rx/RxPanel.tsx mav_gss_lib/web/src/components/rx/PacketList.tsx mav_gss_lib/web/src/App.tsx
git commit -m "Wire adapter columns through App -> RxPanel -> PacketList -> PacketRow"
```

---

## Task 7: Final Build and Verification

- [ ] **Step 1: Clean build**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE/mav_gss_lib/web"
rm -rf dist
npm run build
```

- [ ] **Step 2: Python tests**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
python3 -m pytest tests/ -v

cd "/Users/irfan/Documents/MAVERIC GSS"
python3 -m pytest tests/ -v
```

- [ ] **Step 3: Commit**

```bash
cd "/Users/irfan/Documents/MAVERIC GSS/MAVERIC GSS CODE"
git add -A
git commit -m "Phase 5b-ii complete: frontend renders from adapter-provided rendering slots"
```

---

## Post-Phase 5b-ii State

**What changed:**
- Frontend types include `ColumnDef`, `RenderingData`, `DetailBlock`, `IntegrityBlock`
- `useRxSocket` handles `columns` WebSocket message
- `PacketList` renders column headers from adapter-provided `columns`
- `PacketRow` renders cell values from `_rendering.row` (with hardcoded fallback)
- `PacketDetail` renders from `_rendering.detail_blocks`, `protocol_blocks`, `integrity_blocks` (with hardcoded fallback)
- `RxPanel` and `App.tsx` wire columns through the component tree

**What stays unchanged:**
- Flat MAVERIC fields on `RxPacket` (used by stats, filtering, copy, text export)
- `useRxSocket` stats computation (still uses `crc16_ok`, `is_dup`, `is_echo`)
- `RxPanel` filtering (`hideUplink` uses `is_echo`)
- `RxPanel` text export (`formatPacketText` uses flat fields)
- Context menu copy (uses `p.cmd`, `p.raw_hex`)
- TX components (`QueueItem`, `CommandBuilder`)

**What future cleanup can do:**
- Remove flat MAVERIC fields from `RxPacket` once stats/filtering also go through adapter
- Remove hardcoded fallback branches in `PacketRow` and `PacketDetail`
- Remove Phase 5a transitional adapter methods
