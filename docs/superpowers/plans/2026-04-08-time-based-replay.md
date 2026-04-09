# Time-Based Log Replay Scrubber — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the packet-index replay scrubber with a YouTube-style time-based scrubber using shadcn Slider.

**Architecture:** Primary changes are in `ReplayPanel.tsx`. A new `slider.tsx` is added via shadcn CLI. The slider's value domain changes from packet index to millisecond offset from session start. A binary search helper maps time offsets back to packet indices for the accumulative `replacePackets()` call. A hover tooltip tracks the pointer along the slider track. Production `dist/` is rebuilt at the end.

**Tech Stack:** React, shadcn Slider (`@radix-ui/react-slider`), TypeScript, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-04-08-time-based-replay-design.md`

---

### Task 1: Install shadcn Slider component

**Files:**
- Create: `mav_gss_lib/web/src/components/ui/slider.tsx` (via shadcn CLI)

- [ ] **Step 1: Install the slider**

```bash
cd mav_gss_lib/web
npx shadcn@latest add slider
```

- [ ] **Step 2: Verify the file was created**

```bash
ls src/components/ui/slider.tsx
```

Expected: file exists.

- [ ] **Step 3: Verify build passes**

```bash
cd mav_gss_lib/web
npm run build
```

Expected: build succeeds with no errors.

- [ ] **Step 4: Commit**

```bash
git add mav_gss_lib/web/src/components/ui/slider.tsx mav_gss_lib/web/package.json mav_gss_lib/web/package-lock.json
git commit -m "Add shadcn Slider component for replay scrubber"
```

---

### Task 2: Add binary search helper and time formatting utility

**Files:**
- Modify: `mav_gss_lib/web/src/components/logs/ReplayPanel.tsx`

These are pure utility functions with no UI changes — add them above the `ReplayPanel` component.

- [ ] **Step 1: Add the `findPacketIndexAtTime` binary search function**

Add after the existing `parseReplayTime` function (after line 67):

```tsx
/** Binary search for the last packet with parseReplayTime(pkt) <= targetTime.
 *  Returns the index, or 0 if targetTime is before all packets.
 */
function findPacketIndexAtTime(packets: RxPacket[], targetTime: number): number {
  let lo = 0
  let hi = packets.length - 1
  let result = 0
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1
    if (parseReplayTime(packets[mid]) <= targetTime) {
      result = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return result
}
```

- [ ] **Step 2: Add the `formatTimestamp` helper**

Add directly after `findPacketIndexAtTime`:

```tsx
/** Convert a packet's timestamp to HH:MM:SS for display.
 *  Handles full datetime strings, ISO format, and bare HH:MM:SS.
 */
function formatTimestamp(pkt: RxPacket): string {
  const raw = (pkt.time_utc || pkt.time || '').trim()
  if (!raw) return '--:--:--'

  // ISO format: "2026-04-08T11:58:23.000Z"
  if (raw.length > 10 && raw[10] === 'T') {
    const timePart = raw.slice(11, 19)
    if (timePart.length >= 8) return timePart
  }

  // Full datetime: "2026-04-08 11:58:23 PDT" or "2026-04-08 11:58:23.123"
  const spaceMatch = raw.match(/\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2}:\d{2})/)
  if (spaceMatch) return spaceMatch[1]

  // Bare time: "11:58:23" or "11:58:23.456"
  const bareMatch = raw.match(/^(\d{2}:\d{2}:\d{2})/)
  if (bareMatch) return bareMatch[1]

  return '--:--:--'
}
```

- [ ] **Step 3: Verify build passes**

```bash
cd mav_gss_lib/web && npm run build
```

Expected: build succeeds (functions are defined but not yet called — tree-shaking is fine).

- [ ] **Step 4: Commit**

```bash
git add mav_gss_lib/web/src/components/logs/ReplayPanel.tsx
git commit -m "Add binary search and timestamp format helpers for replay"
```

---

### Task 3: Add time-domain state and compute session bounds

**Files:**
- Modify: `mav_gss_lib/web/src/components/logs/ReplayPanel.tsx`

Replace the packet-index slider domain with a time-based domain. The slider value becomes a millisecond offset from session start.

- [ ] **Step 1: Add time-domain state variables**

Inside the `ReplayPanel` component, after the existing `const entriesRef` / `const intervalsRef` declarations (around line 82), add:

```tsx
const [startTime, setStartTime] = useState(0)
const [sessionDurationMs, setSessionDurationMs] = useState(0)
const startTimeRef = useRef(0)
```

- [ ] **Step 2: Compute session bounds on data load**

In the `useEffect` that fetches session data (the `.then((data: LogEntry[]) => {` callback, around line 94), after the line `const packets = data.map((e, i) => entryToPacket(e, i))` and before the gaps computation, add the session time bounds:

```tsx
        // Compute session time bounds
        const t0 = packets.length > 0 ? parseReplayTime(packets[0]) : 0
        const tEnd = packets.length > 0 ? parseReplayTime(packets[packets.length - 1]) : 0
        const duration = Math.max(tEnd - t0, 0)
        startTimeRef.current = t0
        setStartTime(t0)
        setSessionDurationMs(duration)
```

- [ ] **Step 3: Verify build passes**

```bash
cd mav_gss_lib/web && npm run build
```

Expected: build succeeds. `startTime` state is unused in JSX but that's fine (used by ref in next task). Suppress lint warning for unused `startTime` if needed — it will be used in Task 5.

- [ ] **Step 4: Commit**

```bash
git add mav_gss_lib/web/src/components/logs/ReplayPanel.tsx
git commit -m "Compute session time bounds on replay load"
```

---

### Task 4: Replace scrub handler with time-based seeking

**Files:**
- Modify: `mav_gss_lib/web/src/components/logs/ReplayPanel.tsx`

- [ ] **Step 1: Rewrite `handleScrub` to use time-based seeking**

Replace the existing `handleScrub` callback (lines 187–197) with:

```tsx
  const handleScrub = useCallback((_value: number[]) => {
    const offsetMs = _value[0] ?? 0
    const targetTime = startTimeRef.current + offsetMs
    const idx = findPacketIndexAtTime(entriesRef.current, targetTime)
    posRef.current = idx
    setPosition(idx)
    replacePackets(entriesRef.current.slice(0, idx + 1))
    // If playing, restart the schedule from the new position
    if (playingRef.current) {
      if (timerRef.current) clearTimeout(timerRef.current)
      scheduleNext()
    }
  }, [replacePackets, scheduleNext])
```

Note: the shadcn Slider's `onValueChange` passes `number[]`, not a React `ChangeEvent`. The first element is the slider value.

- [ ] **Step 2: Verify build passes**

```bash
cd mav_gss_lib/web && npm run build
```

Expected: build may fail with a type error because the old `<input type="range" onChange={handleScrub}>` expects a `ChangeEvent`, but `handleScrub` now takes `number[]`. This is expected — proceed directly to Task 5 which replaces the JSX. Do **not** commit if the build fails; combine Tasks 4 and 5 into a single commit instead.

- [ ] **Step 3: Commit (skip if build failed — combine with Task 5)**

```bash
git add mav_gss_lib/web/src/components/logs/ReplayPanel.tsx
git commit -m "Rewrite scrub handler for time-based seeking"
```

---

### Task 5: Replace HTML range input with styled shadcn Slider + timestamp display

**Files:**
- Modify: `mav_gss_lib/web/src/components/logs/ReplayPanel.tsx`

This is the main visual change — swap the `<input type="range">` and position counter for the shadcn Slider and timestamp.

- [ ] **Step 1: Add Slider import**

At the top of `ReplayPanel.tsx`, add:

```tsx
import { Slider } from '@/components/ui/slider'
```

- [ ] **Step 2: Replace the scrubber and position counter JSX**

Find the `{/* Scrubber */}` and `{/* Position counter */}` sections (lines 241–255). Replace both blocks with:

```tsx
      {/* Scrubber */}
      <div className="relative flex-1 group">
        <Slider
          min={0}
          max={sessionDurationMs || 1}
          step={1}
          value={[allEntries.length > 0 ? parseReplayTime(allEntries[position]) - startTime : 0]}
          onValueChange={handleScrub}
          className="w-full cursor-pointer [&_[data-slot=slider-track]]:h-1 [&_[data-slot=slider-track]]:group-hover:h-1.5 [&_[data-slot=slider-track]]:transition-all [&_[data-slot=slider-track]]:bg-[#222222] [&_[data-slot=slider-range]]:bg-amber-400 [&_[data-slot=slider-thumb]]:size-3 [&_[data-slot=slider-thumb]]:opacity-0 [&_[data-slot=slider-thumb]]:group-hover:opacity-100 [&_[data-slot=slider-thumb]]:transition-opacity [&_[data-slot=slider-thumb]]:border-0 [&_[data-slot=slider-thumb]]:bg-amber-400"
        />
      </div>

      {/* Current timestamp */}
      <span className="text-[11px] font-mono tabular-nums shrink-0" style={{ color: colors.dim }}>
        {allEntries.length > 0 ? formatTimestamp(allEntries[position]) : '--:--:--'}
      </span>
```

- [ ] **Step 3: Remove unused `intervals` state setter if present**

The `setIntervals` state setter (line 71) is only used to store gaps for the ref. Check if `intervals` state is still needed — the component only uses `intervalsRef`. If the `intervals` state variable is unused in JSX, keep the setter call but note the `[, setIntervals]` destructure is fine as-is (already ignoring the value).

- [ ] **Step 4: Verify build passes**

```bash
cd mav_gss_lib/web && npm run build
```

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add mav_gss_lib/web/src/components/logs/ReplayPanel.tsx
git commit -m "Replace range input with shadcn Slider and timestamp display"
```

---

### Task 6: Add hover tooltip showing target timestamp

**Files:**
- Modify: `mav_gss_lib/web/src/components/logs/ReplayPanel.tsx`

- [ ] **Step 1: Add tooltip and drag state**

Inside `ReplayPanel`, after the existing state declarations, add:

```tsx
  const [tooltipTime, setTooltipTime] = useState<string | null>(null)
  const [tooltipX, setTooltipX] = useState(0)
  const [dragging, setDragging] = useState(false)
  const scrubberRef = useRef<HTMLDivElement>(null)
```

- [ ] **Step 2: Add pointer event handlers**

Add these callbacks after the existing `handleScrub` callback:

```tsx
  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (dragging) return // hide tooltip during drag — thumb position is sufficient
    const rect = scrubberRef.current?.getBoundingClientRect()
    if (!rect || sessionDurationMs === 0) return
    const fraction = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const offsetMs = fraction * sessionDurationMs
    const targetTime = startTimeRef.current + offsetMs
    const idx = findPacketIndexAtTime(entriesRef.current, targetTime)
    setTooltipTime(formatTimestamp(entriesRef.current[idx]))
    setTooltipX(fraction * 100)
  }, [sessionDurationMs, dragging])

  const handlePointerLeave = useCallback(() => {
    setTooltipTime(null)
  }, [])
```

- [ ] **Step 3: Attach handlers and tooltip to the scrubber wrapper div**

Update the `{/* Scrubber */}` wrapper `<div>` (the `relative flex-1 group` div added in Task 5). Add `onPointerDown` to detect drag start on the Slider, and `onValueCommit` to detect drag end. The tooltip is suppressed while `dragging` is true.

```tsx
      {/* Scrubber */}
      <div
        ref={scrubberRef}
        className="relative flex-1 group"
        onPointerMove={handlePointerMove}
        onPointerLeave={handlePointerLeave}
      >
        {tooltipTime && (
          <div
            className="absolute -top-7 -translate-x-1/2 px-1.5 py-0.5 rounded text-[10px] font-mono tabular-nums pointer-events-none whitespace-nowrap"
            style={{
              left: `${tooltipX}%`,
              backgroundColor: colors.bgPanelRaised,
              color: colors.textSecondary,
              border: `1px solid ${colors.borderSubtle}`,
            }}
          >
            {tooltipTime}
          </div>
        )}
        <Slider
          min={0}
          max={sessionDurationMs || 1}
          step={1}
          value={[allEntries.length > 0 ? parseReplayTime(allEntries[position]) - startTime : 0]}
          onValueChange={handleScrub}
          onPointerDown={() => { setDragging(true); setTooltipTime(null) }}
          onValueCommit={() => setDragging(false)}
          className="w-full cursor-pointer [&_[data-slot=slider-track]]:h-1 [&_[data-slot=slider-track]]:group-hover:h-1.5 [&_[data-slot=slider-track]]:transition-all [&_[data-slot=slider-track]]:bg-[#222222] [&_[data-slot=slider-range]]:bg-amber-400 [&_[data-slot=slider-thumb]]:size-3 [&_[data-slot=slider-thumb]]:opacity-0 [&_[data-slot=slider-thumb]]:group-hover:opacity-100 [&_[data-slot=slider-thumb]]:transition-opacity [&_[data-slot=slider-thumb]]:border-0 [&_[data-slot=slider-thumb]]:bg-amber-400"
        />
      </div>
```

- [ ] **Step 4: Verify build passes**

```bash
cd mav_gss_lib/web && npm run build
```

Expected: build succeeds with no errors.

- [ ] **Step 5: Commit**

```bash
git add mav_gss_lib/web/src/components/logs/ReplayPanel.tsx
git commit -m "Add hover tooltip showing target timestamp on scrubber"
```

---

### Task 7: Build production bundle and visual verification

**Files:**
- Modify: `mav_gss_lib/web/dist/` (rebuilt)

- [ ] **Step 1: Build production bundle**

```bash
cd mav_gss_lib/web && npm run build
```

Expected: build succeeds.

- [ ] **Step 2: Commit dist**

```bash
git add mav_gss_lib/web/dist/
git commit -m "Rebuild dist for time-based replay scrubber"
```

- [ ] **Step 3: Manual verification checklist**

Start the app (`python3 MAV_WEB.py`) and open a log replay session. Verify:

1. Scrubber shows as a thin amber progress bar with dark (`#222222`) track background, not the default browser range input
2. Thumb appears on hover, hidden otherwise
3. Hovering over the track shows a timestamp tooltip (HH:MM:SS) that follows the cursor
4. Tooltip disappears during drag — only the thumb is visible while dragging
5. Tooltip reappears after drag ends (pointer release)
6. Dragging the scrubber seeks to the correct time — packets accumulate up to that point
7. Current timestamp displays to the right of the scrubber (e.g., `11:58:23`), not a packet counter
8. Timestamp formats correctly for full datetime logs, ISO logs, and bare HH:MM:SS logs
9. Playback works at all speeds (1x, 2x, 5x, 10x)
10. Play/pause/stop buttons work as before
11. Arrow keys nudge the scrubber position
12. Slider is keyboard-focusable with visible focus indicator
