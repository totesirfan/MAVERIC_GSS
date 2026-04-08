# Plugin System

The plugin system lets missions provide standalone tool pages beyond the core RX/TX dashboard. Plugins are mission-scoped, convention-discovered, and lazy-loaded.

## What Plugins Are

A plugin is a full-page tool that lives alongside the main dashboard. The operator navigates to it via the header nav and back again. Each plugin gets its own WebSocket connections and manages its own state.

Plugins are distinct from the core adapter contract:

- **Adapter methods** (parse, render, build_tx) — required, called per-packet, run on every mission
- **TX Builder** — optional inline component, mounts inside the TX panel
- **Plugins** — optional standalone pages, navigated to separately

## Architecture

```
App.tsx (route owner)
  ├─ GlobalHeader (always mounted)
  ├─ ?panel=tx|rx  → pop-out panel (takes precedence over ?page=)
  ├─ ?page=null    → <MainDashboard />   (owns useRxSocket + useTxSocket)
  ├─ ?page=imaging → <ImagingPage />     (owns its own sockets)
  └─ modals, toaster
```

### URL Parameter Precedence

Two URL parameters control the top-level view mode:

1. **`?panel=tx|rx`** — pop-out panel mode (pre-existing). Takes absolute precedence. If `?panel=` is present, all other routing is ignored. Pop-out windows render a single panel with no header or navigation.
2. **`?page=<id>`** — plugin page mode. Only evaluated when `?panel=` is absent. Renders the named plugin page with the GlobalHeader and back navigation.
3. **Neither** — normal split-pane dashboard.

Plugin pages cannot be popped out. The `?panel=` parameter is reserved for the core TX/RX panels. If both `?panel=` and `?page=` are present in the URL, `?panel=` wins and `?page=` is ignored.

### Component Ownership

`App.tsx` owns route state and renders the active page component. Each page component is a separate React subtree that mounts/unmounts its own WebSocket hooks:

```
App.tsx
  ├─ GlobalHeader (always mounted)
  ├─ ?panel=tx  → <TxPanel />            ← pop-out, standalone
  ├─ ?panel=rx  → <RxPanel />            ← pop-out, standalone
  ├─ page=null  → <MainDashboard />      ← mounts useRxSocket, useTxSocket
  ├─ page='imaging' → <ImagingPage />    ← mounts its own createSocket('/ws/rx')
  └─ modals, toaster, etc.
```

The main dashboard's `useRxSocket()` / `useTxSocket()` live inside the `MainDashboard` component — not at the App level — so they connect only when the main dashboard is mounted and disconnect when the operator navigates to a plugin page.

Route state is driven by `useState` initialized from `?page=`, updated via `history.pushState`, and synced with `popstate` events for browser back/forward.

## Frontend Structure

```
mav_gss_lib/web/src/plugins/
  registry.ts                    ← platform: discovers builders + page plugins
  maveric/
    TxBuilder.tsx                ← inline TX builder (unchanged behavior)
    plugins.ts                   ← page plugin manifest for MAVERIC
    ImagingPage.tsx              ← imaging plugin page component
```

### Plugin Registry (`registry.ts`)

The registry serves two roles:

1. **TX Builder discovery** — same `getMissionBuilder(missionId)` API as before, using `import.meta.glob('./**/TxBuilder.tsx')` for convention-based discovery
2. **Page plugin discovery** — `getPluginPages(missionId)` loads page manifests from `import.meta.glob('./**/plugins.ts')`

### Plugin Discovery and Config Loading

The `import.meta.glob` calls run at build time — all plugin manifests from all missions are bundled. `getPluginPages(missionId)` filters by mission ID at runtime.

Plugin IDs are mission-scoped, not globally unique. Two missions may both define `id: "imaging"`. This means `?page=imaging` cannot be resolved until the active mission is known from `/api/config`.

Loading strategy:

- **Before config loads:** If `?page=` is set, App renders a lightweight loading state (same spinner/skeleton used elsewhere). No plugin component is mounted yet. This is typically <200ms since config is fetched on mount.
- **After config loads:** `getPluginPages(missionId)` resolves the page ID to the correct mission's component. The plugin page mounts and connects its own sockets.
- **Nav buttons wait for config.** The GlobalHeader only shows plugin buttons after config loads and `missionId` is known. Before config loads, the plugin nav is hidden (same as the existing behavior where mission name shows "..." until config arrives).
- **Mismatched mission/page.** If `?page=imaging` is in the URL but the active mission has no imaging plugin, the page renders a "plugin not found" fallback after config loads.

### Plugin Manifest (`plugins.ts`)

Each mission directory may contain a `plugins.ts` that exports an array of page plugin definitions:

```typescript
import { lazy } from 'react'
import type { PluginPageDef } from '@/plugins/registry'

const plugins: PluginPageDef[] = [
  {
    id: 'imaging',
    name: 'Imaging',
    description: 'Image downlink viewer',
    icon: 'Camera',
    component: lazy(() => import('./ImagingPage')),
  },
]

export default plugins
```

### PluginPageDef Interface

```typescript
import type { LazyExoticComponent, ComponentType } from 'react'

interface PluginPageDef {
  id: string                                      // URL slug: ?page=<id>
  name: string                                    // Display name in nav
  description: string                             // Card description
  icon: string                                    // lucide-react icon name
  component: LazyExoticComponent<ComponentType>   // React.lazy() result
}
```

### Adding a Plugin (Frontend Only)

1. Create a component file in `plugins/<mission>/` (e.g., `MyToolPage.tsx`)
2. Add an entry to `plugins/<mission>/plugins.ts`
3. The registry discovers it automatically — no platform code changes
4. Run `npm run build` and commit `dist/`

## Backend Support

Frontend-only plugins need no backend changes. Plugins that need backend state (like imaging) use two extension points, both mission-owned:

### Plugin Router Discovery

Mission packages can declare backend routers for their plugins. The platform discovers and mounts them automatically at startup — no manual `app.include_router()` edits needed.

**Mission side** — the mission `__init__.py` exposes an optional `get_plugin_routers()` function:

```python
# mav_gss_lib/missions/maveric/__init__.py
def get_plugin_routers():
    """Return FastAPI routers for mission plugins. Called once at app startup."""
    from .imaging import get_imaging_router
    return [get_imaging_router()]
```

The router factory receives no arguments. Each router should set its own prefix (e.g., `/api/plugins/imaging`).

**Platform side** — `app.py` calls `get_plugin_routers()` on the active mission package and mounts whatever comes back:

```python
# mav_gss_lib/web_runtime/app.py (in create_app)
plugin_routers = getattr(mission_pkg, 'get_plugin_routers', lambda: [])()
for router in plugin_routers:
    app.include_router(router)
```

This keeps `app.py` stable as plugins are added or removed. The mission package owns the list.

### Packet Hook (`on_packet_received`)

Plugins that need to observe RX packets (imaging, telemetry aggregators, etc.) hook in through the mission adapter, not by editing `RxService`.

The `MissionAdapter` protocol gets one new optional method:

```python
def on_packet_received(self, pkt) -> list[dict] | None:
    """Called for every parsed RX packet. Return optional extra WS messages.

    The platform calls this in the broadcast loop after parsing, logging,
    and rendering. The adapter dispatches internally to whatever plugin
    state it owns (ImageAssembler, aggregators, etc.).

    Returns None or a list of dicts to broadcast as additional WS messages.
    Each dict must have a 'type' key (e.g., 'imaging_progress').
    """
```

**Platform side** — one generic hook call in `broadcast_loop()`, never changes again:

```python
# In RxService.broadcast_loop(), after normal packet broadcast:
if hasattr(self.runtime.adapter, 'on_packet_received'):
    extra_msgs = self.runtime.adapter.on_packet_received(pkt)
    if extra_msgs:
        for msg in extra_msgs:
            await self._broadcast_json(msg)
```

**Mission side** — the MAVERIC adapter owns `ImageAssembler` and dispatches:

```python
# In MavericMissionAdapter
def __init__(self, cmd_defs, image_dir="images"):
    self.cmd_defs = cmd_defs
    self.image_assembler = ImageAssembler(image_dir)

def on_packet_received(self, pkt):
    md = getattr(pkt, 'mission_data', {}) or {}
    cmd = md.get('cmd')
    if not cmd:
        return None
    cmd_id = cmd.get('cmd_id', '')
    if cmd_id == 'img_cnt_chunks':
        # extract filename, count from typed_args
        ...
        self.image_assembler.set_total(filename, count)
    elif cmd_id == 'img_get_chunk':
        # extract filename, chunk_num, data from typed_args
        ...
        self.image_assembler.feed_chunk(filename, chunk_num, data)
    else:
        return None
    received, total = self.image_assembler.progress(filename)
    return [{"type": "imaging_progress", "filename": filename,
             "received": received, "total": total,
             "complete": self.image_assembler.is_complete(filename)}]
```

This keeps `RxService` clean — it calls one hook, never knows about imaging. Future plugins (telemetry dashboards, file transfer trackers) hook in the same way via `on_packet_received` without any platform code changes.

### REST Endpoints

Plugin endpoints live under `/api/plugins/<plugin_id>/`:

```python
# mav_gss_lib/missions/maveric/imaging.py
from fastapi import APIRouter

def get_imaging_router():
    router = APIRouter(prefix="/api/plugins/imaging")

    @router.get("/status")
    async def status(request: Request):
        ...

    return router
```

### WebSocket Integration

Plugins reuse the existing `/ws/rx` and `/ws/tx` WebSocket endpoints. A plugin page connects to the same sockets and filters for relevant messages. The adapter's `on_packet_received` hook injects plugin-specific message types (e.g., `imaging_progress`) into the existing RX broadcast — no separate WebSocket endpoint needed.

**Tradeoff:** Every `/ws/rx` connection currently receives column metadata plus the in-memory packet backlog (capped at 500 packets), and every `/ws/tx` connection receives the queue/history snapshot. A plugin page that only needs imaging progress still pays this startup cost. This is acceptable for v1 — the backlog is small and bounded, and imaging needs RX packet data anyway. If plugins with narrower data needs are added later, subscription scoping (e.g., a `?subscribe=imaging` query param) can be added to the existing WebSocket endpoints without a protocol change.

## Navigation

The GlobalHeader shows a plugin button when page plugins are available (after config loads). With a single plugin, it navigates directly. When multiple plugins exist, it can be expanded to show a grid.

The Escape key returns to the main dashboard from any plugin page. Browser back/forward navigation works via `history.pushState` and `popstate` events.

## Imaging Plugin

The first plugin is the MAVERIC image downlink viewer. See the imaging page implementation for a complete example of:

- Filtered RX log (only image-related packets)
- Purpose-built TX controls (not the generic CLI)
- Real-time image preview with chunk progress
- Backend integration via `ImageAssembler` + adapter packet hook + REST endpoints

### Backend Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/plugins/imaging/status` | GET | Active files with progress (received/total/complete) |
| `/api/plugins/imaging/files` | GET | List image files on disk |
| `/api/plugins/imaging/chunks/{filename}` | GET | Received chunk indices for one file |
| `/api/plugins/imaging/preview/{filename}` | GET | Serve partial/complete image (no-cache, ETag) |

### WebSocket Messages

The RX broadcast includes `imaging_progress` messages (injected by the adapter's `on_packet_received` hook) when image chunks arrive:

```json
{
  "type": "imaging_progress",
  "filename": "photo_01.jpg",
  "received": 42,
  "total": 100,
  "complete": false
}
```

### Image Assembly

`ImageAssembler` in `mav_gss_lib/missions/maveric/imaging.py` handles chunk reassembly:

- `set_total(filename, count)` — register expected chunk count (from `img_cnt_chunks`)
- `feed_chunk(filename, chunk_num, data)` — store chunk + auto-save partial image
- Writes contiguous chunks from index 0, skipping gaps
- Appends JPEG EOI marker so viewers can open partial files
- Auto-saves to `images/` on every chunk

The assembler is owned by the MAVERIC adapter and fed via `on_packet_received` when `img_cnt_chunks` or `img_get_chunk` responses are parsed.
