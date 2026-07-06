import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Monitor, Plug, PlugZap, Trash2 } from 'lucide-react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { getAccessToken } from '../lib/api'

function base64UrlDecode(value: string): string {
  const base = value.replace(/-/g, '+').replace(/_/g, '/')
  const pad = base.length % 4 === 0 ? '' : '='.repeat(4 - (base.length % 4))
  return atob(base + pad)
}

function getTokenSubject(token: string): string {
  try {
    const parts = token.split('.')
    if (parts.length < 2) return 'anonymous'
    const payload = JSON.parse(base64UrlDecode(parts[1]))
    const sub = String(payload?.sub ?? '').trim()
    return sub || 'anonymous'
  } catch {
    return 'anonymous'
  }
}

function getTerminalSessionKey(token: string): string {
  return `terminal:${window.location.host}:${getTokenSubject(token)}`
}

export default function TerminalPage() {
  const [termCommand, setTermCommand] = useState('bash -il')
  const [termConnected, setTermConnected] = useState(false)
  const [error, setError] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const commandRef = useRef(termCommand)
  commandRef.current = termCommand

  const connectTerminal = () => {
    const existing = wsRef.current
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) return
    const token = getAccessToken()
    if (!token) {
      setError('未登录或 token 已失效')
      return
    }
    setError('')
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/api/openclaw/terminal/ws?token=${encodeURIComponent(token)}`)
    wsRef.current = ws

    ws.onopen = () => {
      setTermConnected(true)
      ws.send(JSON.stringify({
        type: 'init',
        session_key: getTerminalSessionKey(token),
        command: commandRef.current,
      }))
    }
    ws.onmessage = (evt) => {
      const term = termRef.current
      if (!term) return
      try {
        const msg = JSON.parse(String(evt.data))
        if (msg.type === 'output') {
          term.write(String(msg.data ?? ''))
        } else if (msg.type === 'session') {
          term.write(`\r\n[session] ${String(msg.session_key ?? '')} ${msg.reused ? '(reused)' : '(new)'}\r\n`)
        } else if (msg.type === 'started') {
          term.write(`[started] ${String(msg.command ?? '')}\r\n`)
        } else if (msg.type === 'exit') {
          term.write(`\r\n[exit] code=${String(msg.code)} signal=${String(msg.signal)}\r\n`)
        } else if (msg.type === 'error') {
          term.write(`\r\n[error] ${String(msg.message ?? '')}\r\n`)
        }
      } catch {
        term.write(String(evt.data))
      }
    }
    ws.onclose = () => {
      setTermConnected(false)
      termRef.current?.write('\r\n[disconnected] terminal websocket closed\r\n')
    }
    ws.onerror = () => {
      termRef.current?.write('\r\n[error] websocket error\r\n')
    }
  }

  const disconnectTerminal = () => {
    const ws = wsRef.current
    if (!ws) return
    try { ws.close() } catch { /* ignore */ }
    wsRef.current = null
    setTermConnected(false)
  }

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const term = new Terminal({
      fontSize: 13,
      fontFamily: 'Menlo, Monaco, "Courier New", monospace',
      theme: { background: '#000000', foreground: '#b5e8b5', cursor: '#b5e8b5' },
      cursorBlink: true,
      scrollback: 5000,
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(container)
    termRef.current = term

    // Keyboard input → PTY (arrows, enter, ctrl-c, tab, ... all flow through)
    term.onData((data) => {
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'input', data }))
      }
    })

    const doFit = () => { try { fit.fit() } catch { /* ignore */ } }
    doFit()
    const resizeObserver = new ResizeObserver(doFit)
    resizeObserver.observe(container)
    window.addEventListener('resize', doFit)

    // auto-connect on mount
    connectTerminal()

    return () => {
      resizeObserver.disconnect()
      window.removeEventListener('resize', doFit)
      try { wsRef.current?.close() } catch { /* ignore */ }
      wsRef.current = null
      term.dispose()
      termRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="flex h-[calc(100vh-7.5rem)] flex-col">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-dark-text">实时终端</h1>
        <p className="mt-1 text-sm text-dark-text-secondary">完整终端（xterm.js + PTY），支持方向键、Tab 补全、TUI 向导（vi/top/htop）。直接在此输入命令即可。</p>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-accent-red/10 p-3 text-sm text-accent-red flex items-center gap-2">
          <AlertCircle size={16} />
          {error}
        </div>
      )}

      <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-dark-border bg-dark-card">
        <div className="px-5 py-3 border-b border-dark-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Monitor size={16} className="text-dark-text-secondary" />
            <h2 className="text-sm font-semibold text-dark-text">实时终端（xterm.js + PTY）</h2>
          </div>
          <span className={`text-xs ${termConnected ? 'text-accent-green' : 'text-dark-text-secondary'}`}>
            {termConnected ? '已连接' : '未连接'}
          </span>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 px-5 py-4">
          <div className="flex items-center gap-2">
            <input
              value={termCommand}
              onChange={e => setTermCommand(e.target.value)}
              className="flex-1 rounded-lg border border-dark-border bg-dark-bg px-3 py-2 text-sm text-dark-text focus:border-accent-blue focus:outline-none"
              placeholder="启动命令，例如 bash -il"
            />
            <button
              onClick={connectTerminal}
              disabled={termConnected}
              className="inline-flex items-center gap-1 rounded-lg border border-dark-border px-3 py-2 text-xs text-dark-text-secondary hover:text-dark-text disabled:opacity-50"
            >
              <Plug size={14} /> 连接
            </button>
            <button
              onClick={disconnectTerminal}
              disabled={!termConnected}
              className="inline-flex items-center gap-1 rounded-lg border border-dark-border px-3 py-2 text-xs text-dark-text-secondary hover:text-dark-text disabled:opacity-50"
            >
              <PlugZap size={14} /> 断开
            </button>
            <button
              onClick={() => termRef.current?.clear()}
              className="inline-flex items-center gap-1 rounded-lg border border-dark-border px-3 py-2 text-xs text-dark-text-secondary hover:text-dark-text"
              title="清屏"
            >
              <Trash2 size={14} /> 清屏
            </button>
          </div>

          <div ref={containerRef} className="min-h-0 flex-1 overflow-hidden rounded-lg border border-dark-border bg-black p-2" />
        </div>
      </section>
    </div>
  )
}
