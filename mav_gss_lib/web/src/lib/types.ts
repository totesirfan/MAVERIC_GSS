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

// ---- Rendering Slots (architecture spec §4) ----

export interface ColumnDef {
  id: string
  label: string
  width?: string
  align?: 'left' | 'right'
  flex?: boolean
  badge?: boolean
  toggle?: string
}

export interface RenderingFlag {
  tag: string
  tone: string
}

export interface RenderingMeta {
  opacity?: number
}

/** Column values keyed by column ID, plus optional presentation metadata. */
export interface RenderingRow {
  values: Record<string, string | number | RenderingFlag[]>
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

export interface RxStatus {
  zmq: string
  pkt_rate: number
  silence_s: number
}

// ---- TX ----

export interface CmdDisplay {
  title: string
  subtitle?: string
  row: Record<string, string | number>
  detail_blocks: DetailBlock[]
}

export interface TxColumnDef {
  id: string
  label: string
  width?: string
  align?: 'left' | 'right'
  flex?: boolean
  badge?: boolean
  hide_if_all?: string[]
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

export type TxQueueItem = TxQueueCmd | TxQueueDelay

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

export interface TxCapabilities {
  raw_send: boolean
  command_builder: boolean
}

export interface MissionBuilderProps {
  onQueue: (payload: Record<string, unknown>) => void
  onClose: () => void
}

// ---- Config ----

export interface GssConfig {
  nodes: Record<number, string>
  ptypes: Record<number, string>
  node_descriptions?: Record<string, string>
  ax25: {
    src_call: string
    src_ssid: number
    dest_call: string
    dest_ssid: number
  }
  csp: {
    priority: number
    source: number
    destination: number
    dest_port: number
    src_port: number
    flags: number
    csp_crc: boolean
  }
  tx: {
    zmq_addr: string
    frequency: string
    delay_ms: number
    uplink_mode: string
  }
  rx: {
    zmq_addr: string
    zmq_port: number
  }
  general: {
    mission?: string
    mission_name?: string
    rx_title?: string
    tx_title?: string
    version: string
    log_dir: string
    gs_node: string
  }
}

// ---- Logs ----

export interface LogSession {
  id: string
  filename: string
  packets: number
  path: string
}
