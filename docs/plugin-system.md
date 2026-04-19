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
  ├─ ?panel=tx|rx  → PopOutTx / PopOutRx (no header, takes precedence over ?page=)
  └─ AppShell (default)
       ├─ GlobalHeader
       ├─ TabViewport
       │    ├─ activeTabId = '__dashboard__' → <MainDashboard /> (owns useRxSocket + useTxSocket)
       │    └─ activeTabId = '<plugin-id>'   → plugin page component (owns its own sockets)
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
  ├─ ?panel=tx  → <PopOutTx />            ← standalone window, no header
  ├─ ?panel=rx  → <PopOutRx />            ← standalone window, no header
  └─ AppShell (default)
       ├─ GlobalHeader
       ├─ TabViewport (renders by activeTabId)
       │    ├─ '__dashboard__' → <MainDashboard />  ← mounts useRxSocket, useTxSocket
       │    └─ '<plugin-id>'   → plugin page        ← mounts its own sockets
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

- **Before config loads:** The plugins list is empty, so `TabViewport` cannot resolve `?page=<id>` to a component and falls back to its "Plugin not found" view. This is typically <200ms since config is fetched on mount.
- **After config loads:** `getPluginPages(missionId)` resolves the page ID to the correct mission's component. The plugin page mounts (through `Suspense` with a `Skeleton` fallback while the lazy chunk loads) and connects its own sockets.
- **Nav tabs wait for config.** The plugin tabs are appended to the tab strip only after config loads and `missionId` is known (see the `getPluginPages` effect in `AppShell`). Before config loads, only the dashboard tab is present.
- **Mismatched mission/page.** If `?page=imaging` is in the URL but the active mission has no imaging plugin, the page renders a "plugin not found" fallback after config loads.

### Plugin Manifest (`plugins.ts`)

Each mission directory may contain a `plugins.ts` that exports an array of page plugin definitions:

```typescript
import { lazy } from 'react'
import { Camera } from 'lucide-react'
import type { PluginPageDef } from '@/plugins/registry'

const plugins: PluginPageDef[] = [
  {
    id: 'imaging',
    name: 'Imaging',
    description: 'Image downlink viewer',
    icon: Camera,
    category: 'mission',
    order: 10,
    component: lazy(() => import('./ImagingPage')),
  },
]

export default plugins
```

### PluginPageDef Interface

```typescript
import type { LazyExoticComponent, ComponentType } from 'react'
import type { LucideIcon } from 'lucide-react'

interface PluginPageDef {
  id: string                                      // URL slug: ?page=<id>
  name: string                                    // Display name in nav
  description: string                             // Card description
  icon: LucideIcon                                // lucide-react icon component
  component: LazyExoticComponent<ComponentType>   // React.lazy() result
  category: 'mission' | 'platform'                // nav grouping
  keepAlive?: boolean                             // keep mounted when inactive
  order?: number                                  // nav sort order
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

**Mission side** — the mission `__init__.py` exposes an optional `get_plugin_routers(adapter, config_accessor)` function:

```python
# mav_gss_lib/missions/maveric/__init__.py
def get_plugin_routers(adapter=None, config_accessor=None):
    """Return FastAPI routers for mission plugins. Called once at app startup.

    Args:
        adapter: the live mission adapter instance — plugins typically need
                 state owned by the adapter (e.g., ImageAssembler).
        config_accessor: zero-arg callable returning the live merged config
                 dict. Plugin routers that read runtime config (e.g., the
                 imaging router reads ``imaging.thumb_prefix`` for pair
                 grouping) should use this rather than snapshotting config.
    """
    assembler = getattr(adapter, "image_assembler", None) if adapter else None
    if assembler is None:
        return []
    from .imaging import get_imaging_router
    return [get_imaging_router(assembler, config_accessor=config_accessor)]
```

Each router should set its own prefix (e.g., `/api/plugins/imaging`).

**Platform side** — `app.py` calls `get_plugin_routers()` on the active mission package and mounts whatever comes back, passing the live adapter and a config accessor:

```python
# mav_gss_lib/web_runtime/app.py (in create_app)
mission_pkg = importlib.import_module(f"mav_gss_lib.missions.{mission_id}")
get_routers = getattr(mission_pkg, "get_plugin_routers", None)
if get_routers:
    for router in get_routers(runtime.adapter, config_accessor=lambda: runtime.cfg):
        app.include_router(router)
```

This keeps `app.py` stable as plugins are added or removed. The mission package owns the list, and the adapter owns plugin state (assemblers, aggregators, etc.).

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

**Mission side** — the MAVERIC adapter owns `ImageAssembler` (plus `gnc_store`) and dispatches. The adapter is a dataclass whose plugin state is pre-built by `init_mission(cfg)` and passed in by the shared mission loader, so the constructor does not take raw paths:

```python
# In MavericMissionAdapter (illustrative — see adapter.py for the full version)
@dataclass
class MavericMissionAdapter:
    cmd_defs: dict
    nodes: NodeTable
    image_assembler: object = None   # built by init_mission()
    gnc_store: object = None         # built by init_mission()

    def on_packet_received(self, pkt):
        md = getattr(pkt, 'mission_data', {}) or {}
        cmd = md.get('cmd')
        if not cmd or not self.image_assembler:
            return None
        cmd_id = cmd.get('cmd_id', '')
        if cmd_id == 'img_cnt_chunks':
            # extract filename, count from typed_args
            ...
            self.image_assembler.set_total(filename, count)
        elif cmd_id == 'img_get_chunk':
            # extract filename, chunk_num, data, chunk_size from typed_args
            ...
            self.image_assembler.feed_chunk(filename, chunk_num, data, chunk_size=chunk_size)
        else:
            return None
        received, total = self.image_assembler.progress(filename)
        return [{"type": "imaging_progress", "filename": filename,
                 "received": received, "total": total,
                 "complete": self.image_assembler.is_complete(filename)}]
```

`init_mission(cfg)` resolves `general.image_dir` and constructs the `ImageAssembler`, then the shared loader injects it into the adapter alongside `cmd_defs`, `nodes`, and `gnc_store`. Plugins therefore never instantiate their own state — the adapter holds one live instance per plugin resource.

This keeps `RxService` clean — it calls one hook, never knows about imaging. Future plugins (telemetry dashboards, file transfer trackers) hook in the same way via `on_packet_received` without any platform code changes.

### REST Endpoints

Plugin endpoints live under `/api/plugins/<plugin_id>/`:

```python
# mav_gss_lib/missions/maveric/imaging.py
from fastapi import APIRouter

def get_imaging_router(assembler: "ImageAssembler", config_accessor=None):
    router = APIRouter(prefix="/api/plugins/imaging")

    @router.get("/status")
    async def status(request: Request):
        # Uses assembler directly; config_accessor() for live config lookups
        ...

    return router
```

The imaging router exposes `paired_status()` which groups image pairs (full + thumb) by filename prefix — the prefix is read live from `imaging.thumb_prefix` in config via `config_accessor()` so operators can retune it at runtime without restarting. `ImageAssembler.feed_chunk(filename, chunk_num, data, chunk_size=None)` returns `(received, total, complete)`; the optional `chunk_size` kwarg lets the adapter record the declared per-chunk byte length (used by the OBC to strip its C-string terminator) so the pair view can display it.

### WebSocket Integration

Plugins reuse the existing `/ws/rx` and `/ws/tx` WebSocket endpoints. A plugin page connects to the same sockets and filters for relevant messages. The adapter's `on_packet_received` hook injects plugin-specific message types (e.g., `imaging_progress`) into the existing RX broadcast — no separate WebSocket endpoint needed.

**Tradeoff:** Every `/ws/rx` connection currently receives column metadata plus the in-memory packet backlog (capped at 500 packets), and every `/ws/tx` connection receives the queue/history snapshot. A plugin page that only needs imaging progress still pays this startup cost. This is acceptable for v1 — the backlog is small and bounded, and imaging needs RX packet data anyway. If plugins with narrower data needs are added later, subscription scoping (e.g., a `?subscribe=imaging` query param) can be added to the existing WebSocket endpoints without a protocol change.

## Navigation

The GlobalHeader renders a `TabStrip` (`components/layout/TabStrip.tsx`) built from `buildNavigationTabs(plugins)` in `components/layout/navigation.ts`. The dashboard is always the first tab (id `__dashboard__`); each discovered plugin becomes an additional tab, sorted by category (mission first, then platform) and `order`.

Clicking a tab calls `navigateTo(id)` in `App.tsx`, which updates the URL via `history.pushState` and swaps the rendered page in `TabViewport`. Browser back/forward is handled via `popstate`. The Command Palette (Ctrl+K) also exposes the same navigation targets.

## Imaging Plugin

The first plugin is the MAVERIC image downlink viewer. See the imaging page implementation for a complete example of:

- Filtered RX log (only image-related packets)
- Purpose-built TX controls (not the generic CLI)
- Real-time image preview with chunk progress
- Backend integration via `ImageAssembler` + adapter packet hook + REST endpoints

### Backend Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/plugins/imaging/status` | GET | Active files with progress (received/total/complete), grouped into full/thumb pairs |
| `/api/plugins/imaging/files` | GET | List image files on disk |
| `/api/plugins/imaging/chunks/{filename}` | GET | Received chunk indices for one file |
| `/api/plugins/imaging/preview/{filename}` | GET | Serve partial/complete image (no-cache, ETag) |
| `/api/plugins/imaging/file/{filename}` | DELETE | Remove image, meta sidecar, chunk dir, and in-memory state |

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
- `feed_chunk(filename, chunk_num, data, chunk_size=None)` — store chunk + auto-save partial image; optional `chunk_size` records the declared per-chunk byte length
- Writes contiguous chunks from index 0, skipping gaps
- Appends JPEG EOI marker so viewers can open partial files
- Auto-saves to `images/` on every chunk
- `delete_file(filename)` — remove image, meta sidecar, chunk directory, and in-memory state (backs the DELETE endpoint)

The assembler is owned by the MAVERIC adapter and fed via `on_packet_received` when `img_cnt_chunks` or `img_get_chunk` responses are parsed.

## GNC Plugin

MAVERIC also ships a second plugin — the GNC register dashboard — mounted through the same `get_plugin_routers(adapter, config_accessor)` mechanism. It serves as a second reference implementation for the plugin contract:

- **Backend router** — `mav_gss_lib/missions/maveric/telemetry/gnc_router.py` exposes the router under prefix `/api/plugins/gnc` with `GET /snapshot`, `DELETE /snapshot` (broadcasts `gnc_snapshot_cleared` on `/ws/rx`), and `GET /catalog`.
- **Adapter state** — the adapter carries a `gnc_store` (`GncRegisterStore`) built by `init_mission()` at `<log_dir>/.gnc_snapshot.json`. `on_packet_received` decodes `mtq_get_1` RES packets and pushes snapshots to the store, emitting `gnc_register_update` WS messages on `/ws/rx`.
- **Frontend page** — `mav_gss_lib/web/src/plugins/maveric/gnc/GNCPage.tsx`, registered in `mav_gss_lib/web/src/plugins/maveric/plugins.ts` with `id: 'gnc'`, `keepAlive: true` so hook state survives tab switches.

The GNC plugin is discovered and mounted identically to imaging — no platform changes were needed to add it.
