// ---- RX ----

export interface RxPacket {
  num: number
  time: string
  time_utc: string
  frame: string
  size: number
  raw_hex: string
  warnings: string[]
  is_echo: boolean
  is_dup: boolean
  is_unknown: boolean
  _rendering?: RenderingData
}

// ---- Rendering Slots ----

export interface ColumnDef {
  id: string
  label: string
  width?: string
  align?: 'left' | 'right'
  flex?: boolean
  toggle?: string
}

export interface RenderingFlag {
  tag: string
  tone: string
}

export interface RenderingMeta {
  opacity?: number
}

export interface RenderCell {
  value: string | number | boolean | null | RenderingFlag[]
  tone?: string | null
  badge?: boolean
  tooltip?: string | null
  monospace?: boolean
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
  row: Record<string, RenderCell>
  meta?: RenderingMeta
  detail_blocks: DetailBlock[]
  protocol_blocks: DetailBlock[]
  integrity_blocks: IntegrityBlock[]
}

export interface RxStatus {
  zmq: string
  pkt_rate: number
  silence_s: number
}

// ---- TX ----

export interface CmdDisplay {
  title: string
  subtitle?: string
  row: Record<string, RenderCell>
  detail_blocks: DetailBlock[]
}

export interface TxColumnDef {
  id: string
  label: string
  width?: string
  align?: 'left' | 'right'
  flex?: boolean
  hide_if_all?: string[]
}

export interface ColumnDefs {
  rx: ColumnDef[]
  tx: TxColumnDef[]
}

export interface TxQueueCmd {
  type: 'mission_cmd'
  num: number
  display: CmdDisplay
  guard: boolean
  size: number
  payload: Record<string, unknown>
}

export interface TxQueueDelay {
  type: 'delay'
  delay_ms: number
}

export interface TxQueueNote {
  type: 'note'
  text: string
}

export type TxQueueItem = TxQueueCmd | TxQueueDelay | TxQueueNote

export interface TxQueueSummary {
  cmds: number
  guards: number
  est_time_s: number
}

export interface TxHistoryItem {
  n: number
  ts: string
  type: 'mission_cmd'
  display: CmdDisplay
  payload: Record<string, unknown>
  size: number
  // Join key to the verification Map. Stamped by backend `_record_sent`;
  // the same id is used as `CommandInstance.cmd_event_id` when the instance
  // is registered. Optional because legacy history rows won't have it.
  event_id?: string
}

export interface SendProgress {
  sent: number
  total: number
  current: string
  waiting?: boolean
}

export interface GuardConfirm {
  index: number
  display: CmdDisplay
}

// ---- Unified TX timeline ----
// Per-row lifecycle. Only `pending` / `sending` / `complete` are reached
// today; `released` / `accepted` / `failed` / `timed_out` are reserved for
// the planned command-verification feature. Adding a state here does not
// require any layout change.
export type TxRowStatus =
  | 'pending'
  | 'sending'
  | 'released'
  | 'accepted'
  | 'complete'
  | 'failed'
  | 'timed_out'

export interface TxDisplayItem {
  // Stable DOM/dnd-kit key. Pending: `q-<counter>`. Sent: `h-<TxHistoryItem.n>`.
  uid: string
  status: TxRowStatus
  source: 'queue' | 'history'
  // Queue index for queue items — used for delete/guard/duplicate/reorder.
  queueIndex?: number
  historyN?: number
  item: TxQueueItem | TxHistoryItem
}

// Optimistic drag-reorder override: short-lived local reshuffle of the
// pending segment, applied on top of the backend queue until the backend
// echoes the reorder back. Keeps drag-and-drop snappy.
export interface PendingReorderOverride {
  // Array of queue indices in the desired new order (e.g. [2, 0, 1, 3]).
  order: number[]
  // Monotonic token bumped each time the override is installed. Cleared
  // when `queue` length changes (i.e. backend echoed, or queue shrank
  // from a send).
  token: number
}

export interface TxCapabilities {
  mission_commands: boolean
}

export interface MissionBuilderProps {
  onQueue: (payload: Record<string, unknown>) => void
  onClose: () => void
  disabled?: boolean
}

// ---- Config ----
// Native split shape returned by GET /api/config and accepted by PUT /api/config.
// Matches the backend WebRuntime primary state: {platform_cfg, mission_id, mission_cfg}.

export interface PlatformConfig {
  tx: {
    zmq_addr: string
    frequency: string
    delay_ms: number
    uplink_mode: string
  }
  rx: {
    zmq_addr: string
    tx_blackout_ms?: number
  }
  general: {
    version: string
    build_sha?: string
    log_dir: string
    generated_commands_dir?: string
  }
  stations?: Record<string, string>
}

export interface Maveric_Ax25Config {
  src_call: string
  src_ssid: number
  dest_call: string
  dest_ssid: number
}

export interface MavericCspConfig {
  priority: number
  source: number
  destination: number
  dest_port: number
  src_port: number
  flags: number
  csp_crc: boolean
}

export interface MavericMissionConfig {
  mission_name?: string
  rx_title?: string
  tx_title?: string
  gs_node?: string
  nodes?: Record<string, string>
  ptypes?: Record<string, string>
  node_descriptions?: Record<string, string>
  ax25: Maveric_Ax25Config
  csp: MavericCspConfig
  imaging?: Record<string, unknown>
}

export interface GssConfig {
  platform: PlatformConfig
  mission: {
    id: string
    config: MavericMissionConfig
  }
}

// ---- Preflight ----

export interface PreflightCheck {
  group: string
  label: string
  status: 'ok' | 'fail' | 'warn' | 'skip'
  fix: string
  detail: string
  meta?: UpdatesCheckMeta | null
}

export interface PreflightSummary {
  total: number
  passed: number
  failed: number
  warnings: number
  skipped?: number
  ready: boolean
}

// ---- Updater ----

export interface UpdatesCheckMeta {
  branch: string
  current_sha: string
  behind_count: number
  commits: { sha: string; subject: string }[]
  missing_pip_deps: string[]
  dirty: boolean
  button: 'apply' | null
  button_disabled: boolean
  button_reason: string | null
  fetch_error?: string
}

export type UpdatePhase = 'git_pull' | 'countdown' | 'restart'

export type UpdateUIState = 'idle' | 'confirming' | 'applying' | 'failed' | 'reloading'

export interface UpdateProgress {
  phase: UpdatePhase
  status: 'pending' | 'running' | 'ok' | 'fail'
  detail?: string
}

// ---- Command verification ----

export type VerifierStage = 'received' | 'accepted' | 'complete' | 'failed'
export type VerifierState = 'pending' | 'passed' | 'failed' | 'window_expired'
export type InstanceStage =
  | 'released' | 'received' | 'accepted' | 'complete' | 'failed' | 'timed_out'

export interface CheckWindow {
  start_ms: number
  stop_ms: number
}

export interface VerifierSpec {
  verifier_id: string
  stage: VerifierStage
  check_window: CheckWindow
  display_label: string
  display_tone: 'info' | 'success' | 'warning' | 'danger' | 'neutral'
}

export interface VerifierOutcome {
  state: VerifierState
  matched_at_ms: number | null
  match_event_id: string | null
}

export interface CommandInstance {
  instance_id: string
  correlation_key: Array<string | number>
  t0_ms: number
  cmd_event_id: string
  verifier_set: { verifiers: VerifierSpec[] }
  outcomes: Record<string, VerifierOutcome>
  stage: InstanceStage
}
