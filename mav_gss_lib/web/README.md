# MAVERIC GSS Web Console

This directory contains the React/Vite operator console for MAVERIC GSS.

It is not a standalone app. It is the frontend for the FastAPI runtime under `mav_gss_lib/web_runtime/`. The current built frontend lives in `dist/` (committed) and is served directly by the Python backend — no separate deploy step.

## What Lives Here

- RX monitoring views
- TX queue and command-builder views
- Config sidebar and runtime config editor
- Log browser and replay controls
- Preflight/updater bootstrap screens
- Shared layout, keyboard shortcuts, and operator feedback components
- Mission-scoped plugin pages (e.g. imaging viewer)

## Tech Stack

- **React 19** + **Vite 8** + **TypeScript**
- **Tailwind CSS v4** + **shadcn/ui** (base-nova preset)
- **@base-ui/react**, **@radix-ui/react-context-menu** — unstyled UI primitives
- **framer-motion** — animation
- **@dnd-kit/\*** — drag-and-drop for TX queue reorder
- **react-resizable-panels** — split-pane layout
- **react-virtuoso** — virtualized packet/history lists
- **cmdk** — Ctrl+K command palette
- **sonner** — toast notifications
- **lucide-react** — iconography
- **react-day-picker** — date handling (bundles its own `date-fns` transitively)
- **Fonts:** `@fontsource-variable/inter` (UI text), `@fontsource-variable/jetbrains-mono` (data rows) — both declared as `@font-face` in `src/index.css`.

See `package.json` for the exact version, which is single-sourced into the backend via `mav_gss_lib/config.py::_read_version()`.

## Build

```bash
cd mav_gss_lib/web
npm install
npm run dev            # Vite HMR on :5173, proxies /api + /ws to :8080
npm run build          # tsc -b && vite build → emits dist/
npm run lint
```

`npm run build` runs `tsc -b` first to catch type errors, then bundles with Vite. The built assets land in `mav_gss_lib/web/dist/` and are served by the backend. **After any UI source change, run `npm run build` and commit `dist/` alongside the source.**

The backend (`python3 MAV_WEB.py`) must be running alongside `npm run dev` for API/WebSocket proxying to work.

## Directory Layout

```
src/
  App.tsx                Top-level router (?panel= pop-out, ?page= plugins, else AppShell → MainDashboard)
  main.tsx               React root; mounts <App /> and imports index.css
  index.css              Tailwind directives, token definitions, and @font-face declarations
  components/
    MainDashboard.tsx    Split-pane RX/TX layout, owns useRxSocket/useTxSocket
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
  hooks/
    RxProvider.tsx       RX WebSocket context
    TxProvider.tsx       TX WebSocket + queue context
    SessionProvider.tsx  Log session state
    useRxSocket.ts       RX socket hook
    useTxSocket.ts       TX socket hook
    useSession.ts        Log session operations
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
    types.ts             Shared types
    nodes.ts             Node resolution helpers
    auth.ts              Session token handling
    ws.ts                WebSocket helpers
    utils.ts
  plugins/
    registry.ts          Convention-based plugin discovery via import.meta.glob
    maveric/
      TxBuilder.tsx      MAVERIC command picker (mission TX builder)
      plugins.ts         Plugin page manifest
      ImagingPage.tsx    Imaging downlink viewer
      imaging/           Imaging subcomponents

dist/                    Production build (committed)
```

## URL Modes

| URL | Renders |
|---|---|
| `/` | `MainDashboard` — RX/TX split pane |
| `/?panel=rx` or `/?panel=tx` | Pop-out single-panel window (no header, no nav) |
| `/?page=<plugin-id>` | Mission plugin page (e.g. `?page=imaging`) |

`?panel=` takes precedence over `?page=`. Plugin pages cannot be popped out.

See `docs/plugin-system.md` for the full plugin contract (frontend + backend).

## Runtime Contract

The web app should consume normalized runtime data, not mission-specific packet internals.

In practice that means:

- Packet parsing and protocol truth belong in `mav_gss_lib/missions/<mission>/adapter.py`
- Backend packet shaping belongs in `mav_gss_lib/web_runtime/rx_service.py` / `tx_service.py`
- React components should render the normalized packet/queue/config models they receive

If adapting this repository for a future SERC mission requires widespread React changes just to support a different packet format, the backend mission boundary is probably leaking.

## Development Guidance

- Keep mission naming and operator-facing labels config-driven where practical
- Treat protocol-detail sections as optional UI blocks, not universal assumptions
- Prefer extending the normalized packet/queue shape over teaching React components new mission parsing rules
- Follow NASA HFDS color/contrast guidance — see `CLAUDE.md` for the semantic color tokens and minimums
- For mission-specific TX builders or plugin pages, place them under `src/plugins/<mission>/` — the registry discovers them automatically via `import.meta.glob`
