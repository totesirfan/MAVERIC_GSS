export function createSocket(
  path: string,
  onMessage: (data: unknown) => void,
  onStatusChange?: (connected: boolean) => void,
): { send: (msg: unknown) => void; close: () => void } {
  let ws: WebSocket | null = null
  let closed = false
  let retryTimeout: ReturnType<typeof setTimeout> | null = null

  function connect() {
    if (closed) return
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    ws = new WebSocket(`${proto}//${location.host}${path}`)
    ws.onopen = () => onStatusChange?.(true)
    ws.onmessage = (e) => {
      try { onMessage(JSON.parse(e.data)) } catch { /* ignore */ }
    }
    ws.onclose = () => {
      onStatusChange?.(false)
      if (!closed) retryTimeout = setTimeout(connect, 2000)
    }
    ws.onerror = () => ws?.close()
  }
  connect()
  return {
    send(msg: unknown) { if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg)) },
    close() { closed = true; if (retryTimeout) clearTimeout(retryTimeout); ws?.close() },
  }
}
