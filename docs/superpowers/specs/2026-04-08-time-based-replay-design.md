# Time-Based Log Replay Scrubber

## Overview

Replace the packet-index-based replay scrubber with a YouTube-style time-based scrubber. Operators navigate replayed sessions by timestamp rather than packet number, with smooth seeking, a hover tooltip showing target time, and a polished progress bar built on the shadcn Slider (Radix UI).

## Requirements

- Scrubber navigates by **time** (millisecond offset from session start), not packet index
- Current timestamp displayed to the right of the scrubber (e.g., `11:58:23`), replacing the `42/187` counter
- YouTube-style progress bar: thin track, hover-expand, round thumb visible on hover/drag
- Hover tooltip follows cursor along the track, showing the timestamp you'd jump to
- Accumulative view: scrubbing to a time shows all packets from session start through that time
- Playback engine unchanged (inter-packet delays, speed cycling 1x/2x/5x/10x)
- No backend changes required

## Scrubber Component

### Slider

Replace the HTML `<input type="range">` with a shadcn `Slider` (`@radix-ui/react-slider`).

- **Track**: ~4px tall, `colors.borderSubtle` background, expands to ~6px on hover via CSS transition
- **Range fill**: `colors.warning` (amber) showing progress through the session
- **Thumb**: 12px circle, hidden by default, appears on hover/drag with `colors.warning` fill
- **Keyboard**: Arrow keys for fine-grained scrubbing (inherited from Radix)

### Hover Tooltip

A positioned `<div>` that tracks the pointer's X coordinate along the slider track:

- Convert pointer X to a proportional time offset within the session
- Display as timestamp (HH:MM:SS) in a small floating label above the track
- Styled: dark background, light text, ~11px font, slight rounded corners
- Visible only on hover, hidden during drag (thumb position is sufficient)

### Installation

```bash
cd mav_gss_lib/web
npx shadcn@latest add slider
```

## Time Mapping & Seeking

### Data Model

Current: slider ranges `0` to `entries.length - 1` (packet index).

New: slider ranges `0` to `sessionDurationMs` (total session duration in milliseconds).

On load:
1. Compute `startTime = parseReplayTime(entries[0])`
2. Compute `endTime = parseReplayTime(entries[entries.length - 1])`
3. `sessionDurationMs = endTime - startTime`
4. Slider value = `parseReplayTime(currentPacket) - startTime`

### Seeking (scrub handler)

On slider value change:
1. Convert slider value to absolute timestamp: `targetTime = startTime + sliderValue`
2. Binary search the packet array for the last packet with `parseReplayTime(pkt) <= targetTime`
3. Set position to that index
4. Call `replacePackets(entries.slice(0, foundIndex + 1))`

Binary search is needed because packets are sorted by time but multiple packets can share the same timestamp.

### Timestamp Display

Replace the `{position + 1}/{total}` counter with the current packet's formatted timestamp:
- Extract from `entries[position].time` (already `HH:MM:SS` format)
- Displayed in the same location, same styling (11px, tabular-nums, `colors.dim`)

### Playback Engine

Unchanged. The tick engine still advances by packet index using inter-packet delay intervals. The only change is that after each tick, the slider value updates to reflect the new packet's time offset rather than its index.

## Files Changed

| File | Change |
|---|---|
| `components/ui/slider.tsx` | New — installed via shadcn CLI |
| `components/logs/ReplayPanel.tsx` | Slider swap, time mapping, hover tooltip, timestamp display |

## What Stays the Same

- Play/pause/stop buttons and their behavior
- Speed cycling (1x/2x/5x/10x)
- `replacePackets()` accumulative display
- `parseReplayTime()` function
- Inter-packet delay computation
- Data fetching (`/api/logs/{sessionId}`) and normalization
- All backend code
