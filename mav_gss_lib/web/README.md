# MAVERIC GSS Web Console

This directory contains the React/Vite operator console for MAVERIC GSS.

It is not a standalone app. It is the frontend for the FastAPI runtime under `mav_gss_lib/web_runtime/`. The current built frontend lives in `dist/` (committed) and is served directly by the Python backend — no separate deploy step.

## What lives here

- RX monitoring views
- TX queue and command-builder views
- Config sidebar and runtime config editor
- Log browser and replay controls
- Preflight/updater bootstrap screens
- Shared layout, keyboard shortcuts, and operator feedback components
- Mission-scoped plugin pages (e.g. imaging viewer)

## Tech stack

Verified against `package.json`:

- **React 19** + **Vite 8** + **TypeScript 5.9**
- **Tailwind CSS v4** (via `@tailwindcss/vite`) + **shadcn/ui**
- **@base-ui/react**, **@radix-ui/react-context-menu** — unstyled UI primitives
- **framer-motion** — animation
- **@dnd-kit/core**, **@dnd-kit/sortable**, **@dnd-kit/utilities** — drag-and-drop for TX queue reorder
- **react-resizable-panels** — split-pane layout
- **react-virtuoso** — virtualized packet/history lists
- **cmdk** — Ctrl+K command palette (filter in `src/lib/cmdkFilter.ts`)
- **sonner** — toast notifications
- **lucide-react** — iconography
- **react-day-picker** — date picker used in log filters
- **d3-geo**, **topojson-client**, **satellite.js** — globe and orbit visualization
- **class-variance-authority**, **clsx**, **tailwind-merge**, **tw-animate-css** — class composition / motion utilities
- **Fonts:** `@fontsource-variable/inter` (UI), `@fontsource-variable/jetbrains-mono` (data rows). Declared in `src/index.css`.

The frontend version in `package.json` is the single source of truth and is read by the backend via `mav_gss_lib/config.py::_read_version()`. Do not hardcode the version anywhere else.

## Build

```bash
cd mav_gss_lib/web
npm install
npm run dev            # Vite HMR, proxies /api and /ws to :8080
npm run build          # tsc -b && vite build → emits dist/
npm run lint
```

`npm run build` runs `tsc -b` first to catch type errors, then bundles with Vite. Built assets land in `mav_gss_lib/web/dist/` and are served by the FastAPI backend. `dist/` is committed to the repo; `node_modules/` is untracked.

After any UI source change, run `npm run build` and commit the refreshed `dist/` alongside the source changes. The baked build SHA is refreshed only during `vite build`, so every commit that touches `src/` needs a matching `dist/` update.

The backend (`python3 MAV_WEB.py`) must be running alongside `npm run dev` for API and WebSocket proxying to work.

## Directory layout

```
src/
  App.tsx                Top-level router (?panel= pop-out, ?page= plugins, else AppShell → MainDashboard)
  main.tsx               React root; mounts <App /> and imports index.css
  index.css              Tailwind directives, token definitions, and @font-face declarations
  vite-env.d.ts          Vite ambient types (including __BUILD_SHA__)
  components/
    MainDashboard.tsx    Split-pane RX/TX layout; reads RX/TX state via provider hooks
    rx/                  RxPanel, PacketList/Row/Detail, SessionBanner, BlackoutPill
    tx/                  TxPanel, TxQueue, QueueItem, CommandInput, ImportDialog, SentHistory,
                         DelayItem, NoteItem
    shared/              PtypeBadge, StatusDot, TogglePill, ContextMenu, CommandPalette, HelpModal,
                         StatusToast, AlarmStrip, ConfirmBar/Dialog, PromptDialog, PreflightScreen,
                         RenderingBlocks, PlanetGlobe
    config/              Runtime config editor + sidebar
    logs/                Log session browser + replay controls
    layout/              GlobalHeader, SplitPane, KeyboardHintBar, TabStrip, TabViewport,
                         TabActiveContext, navigation (tab builder)
    ui/                  shadcn/ui primitives
  state/                 Providers and store modules (context lives here, not in hooks/)
    SessionProvider.tsx  Session context provider
    sessionContexts.ts   Session context objects
    session.ts           Session hooks and selectors
    TxProvider.tsx       TX WebSocket + queue provider
    txContexts.ts        TX context objects
    tx.ts                TX hooks and selectors
    RxProvider.tsx       RX WebSocket provider
    rxContexts.ts        RX context objects
    rx.ts                RX hooks and selectors
  hooks/                 Pure hooks (no providers)
    useRxSocket.ts       RX socket hook
    useTxSocket.ts       TX socket hook
    useSession.ts        Session operations
    useLogQuery.ts       Paginated log fetching
    useRxToggles.ts      RX panel toggle state
    useReceivingDetection.ts  Silence/burst detection
    useShortcuts.ts      Global keyboard shortcuts
    useAlarms.ts         Alarm strip state
    usePluginServices.ts Plugin service discovery
    usePopOutBootstrap.ts Bootstrap for pop-out windows
    usePreflight.ts      Preflight state subscription
    useDebouncedValue.ts
  lib/
    colors.ts            Semantic tone tokens (danger/warning/info/success/active/neutral)
    columns.ts           Column-driven rendering helpers
    types.ts             Shared types (RxPacket, RxStatus, ColumnDef, etc.)
    nodes.ts             Node resolution helpers
    auth.ts              Session token handling
    ws.ts                WebSocket helpers (createSocket)
    utils.ts             Misc DOM/utility helpers (isInputFocused, cn)
    cmdkFilter.ts        Filter predicate for the Ctrl+K command palette
  plugins/
    registry.ts          Convention-based plugin discovery via import.meta.glob
    maveric/
      TxBuilder.tsx      MAVERIC command picker (mission TX builder)
      plugins.ts         Plugin page manifest
      ImagingPage.tsx    Imaging downlink viewer
      imaging/           Imaging subcomponents
      gnc/               GNC dashboard widgets (attitude/nav/control)

dist/                    Production build (committed)
```

Providers are deliberately placed under `src/state/` rather than `src/hooks/`. `src/hooks/` contains only `use*` hooks; anything that wraps the tree in a `Context.Provider` lives in `src/state/`.

## Provider tree

`App.tsx` wraps the shell in this order (outermost first):

1. `SessionProvider` — session identity, rename/new-session state
2. `TxProvider` — TX WebSocket, queue, guard/send/history
3. `RxProvider` — RX WebSocket, packets, status, display toggles
4. `AppShell` — renders `GlobalHeader`, `TabViewport`, and lazy-loaded modals (`ConfigSidebar`, `LogViewer`, `HelpModal`, `CommandPalette`)

Pop-out windows (`?panel=tx` / `?panel=rx`) are rendered outside the provider tree; they bootstrap their own config via `usePopOutBootstrap` and open their own sockets via `useTxSocket` / `useRxSocket`.

## URL modes

Verified in `src/App.tsx`:

| URL | Renders |
|---|---|
| `/` | `AppShell` with `MainDashboard` — RX/TX split pane, tabs, shell modals |
| `/?page=<plugin-id>` | Mission plugin page in the active tab (e.g. `?page=imaging`, `?page=gnc`) |
| `/?panel=tx` | Pop-out TX panel only (no header, no providers) |
| `/?panel=rx` | Pop-out RX panel only (no header, no providers) |

`?panel=` takes precedence over `?page=`. Plugin pages cannot be popped out. The `tab=` query parameter selects a sub-tab inside a plugin page.

## Runtime contract

The frontend talks to the FastAPI backend in `mav_gss_lib/web_runtime/` over a fixed set of HTTP and WebSocket endpoints. Everything the UI renders should come from these — no packet parsing or command framing happens in React.

WebSocket endpoints:

| Path | Purpose |
|---|---|
| `/ws/rx` | RX packet stream (parsed, with `_rendering` payload) |
| `/ws/tx` | TX queue ops: `queue` (raw CLI), `queue_mission_cmd` (mission builder), send/abort/guard/reorder |
| `/ws/session` | Session identity, new-session and rename events |
| `/ws/preflight` | Preflight check state and updater progress |

HTTP endpoints (see `mav_gss_lib/web_runtime/api/`):

| Path | Purpose |
|---|---|
| `GET /api/status` | Basic health and version |
| `GET /api/selfcheck` | Self-check results |
| `GET /api/config` | Merged runtime config (platform + mission) |
| `PUT /api/config` | Persist operator-overridable keys to `gss.yml` |
| `GET /api/schema` | Mission command schema |
| `GET /api/columns` | RX column definitions |
| `GET /api/tx-columns` | TX queue column definitions |
| `GET /api/tx/capabilities` | Mission TX capabilities (builder metadata) |
| `GET /api/logs` | List log sessions |
| `GET /api/logs/{session_id}` | Fetch log records for replay |
| `GET /api/session` | Current session info |
| `POST /api/session/new` | Start a new session |
| `PATCH /api/session` | Rename the current session tag |
| `GET /api/import-files` | List importable queue files |
| `GET /api/import/{filename}/preview` | Preview a queue import |
| `POST /api/import/{filename}` | Apply a queue import |
| `POST /api/export-queue` | Export the current queue |

Boundaries:

- Packet parsing and protocol truth belong in `mav_gss_lib/missions/<mission>/adapter.py`
- Backend packet shaping belongs in `mav_gss_lib/web_runtime/rx_service.py` and `tx_service.py`
- React components render the normalized packet, queue, and config models they receive — they do not decode wire formats
- Mission-scoped UI (TX builders, plugin pages) lives under `src/plugins/<mission>/` and is discovered by `src/plugins/registry.ts` via `import.meta.glob`

If adapting this repository for another mission requires widespread React changes just to support a different packet format, the backend mission boundary is probably leaking.

## Development guidance

- Keep mission naming and operator-facing labels config-driven where practical
- Treat protocol-detail sections as optional UI blocks, not universal assumptions
- Prefer extending the normalized packet/queue shape over teaching React components new mission parsing rules
- Follow NASA HFDS color/contrast guidance — see `CLAUDE.md` for the semantic color tokens and minimums
- For mission-specific TX builders or plugin pages, place them under `src/plugins/<mission>/`; `registry.ts` discovers them automatically
