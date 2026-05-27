import { useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Plus,
  Send,
  Loader2,
  Trash2,
  Pencil,
  MessageSquare,
  Bot,
  User,
  RefreshCw,
  ChevronRight,
  Paperclip,
  X,
  FileText,
  Copy,
  Check,
} from 'lucide-react'
import MarkdownContent from '../components/MarkdownContent'
import { useNotifications } from '../components/NotificationProvider'
import {
  listSessions,
  getSession,
  deleteSession,
  updateSessionTitle,
  sendChatMessage,
  getRunEventsStreamUrl,
  waitForAgentRun,
  listAgents,
  listSlashCommands,
  uploadFileToWorkspace,
} from '../lib/api'
import type { Session, SessionDetail, AgentInfo, ChatMessage } from '../lib/api'
import { ToolCallGroupCard, ThinkingCard, LiveToolCallsCard, LiveReasoningCard, groupToolCalls, type ToolCallGroup, type LiveToolCallInfo } from '../components/CollapsibleCard'
import {
  buildSlashCommandItems,
  CATEGORY_LABELS,
  filterSlashCommands,
  getSlashQuery,
  type SlashCommandItem,
} from '../lib/slashCommands'

interface PendingFile {
  id: string
  file: File
  name: string
  isImage: boolean
  previewUrl?: string
}

function isImageFile(file: File): boolean {
  return file.type.startsWith('image/')
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/**
 * Extract agentId from session key.
 * Format: agent:<agentId>:session-<timestamp>
 */
function getAgentIdFromKey(key: string): string {
  const parts = key.split(':')
  if (parts.length >= 2 && parts[0] === 'agent') return parts[1]
  return 'main'
}

/**
 * Get the workspace upload dir for an agent.
 * main agent → workspace/uploads
 * other agents → workspace-<agentId>/uploads
 */
function getUploadDir(agentId: string): string {
  if (agentId === 'main') return 'workspace/uploads'
  return `workspace-${agentId}/uploads`
}

export default function Chat() {
  const { registerPendingSession, clearPendingSession } = useNotifications()
  const [searchParams, setSearchParams] = useSearchParams()

  // Sessions
  const [sessions, setSessions] = useState<Session[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(true)
  const [activeSessionKey, setActiveSessionKey] = useState<string | null>(null)
  const [renamingSessionKey, setRenamingSessionKey] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [renameSaving, setRenameSaving] = useState(false)

  // Chat
  const [messages, setMessages] = useState<SessionDetail['messages']>([])
  const [chatLoading, setChatLoading] = useState(false)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [agentRunning, setAgentRunning] = useState(false)
  const [error, setError] = useState('')
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null)
  // Live streaming state: tool calls and reasoning shown in real-time
  const [liveToolCalls, setLiveToolCalls] = useState<LiveToolCallInfo[]>([])
  const [liveReasoning, setLiveReasoning] = useState('')
  // Typewriter streaming: targetText is the full text from SSE, displayedText is what's shown
  const [displayedText, setDisplayedText] = useState('')
  const targetTextRef = useRef('')
  const typewriterTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const setStreamingText = useCallback((text: string) => {
    if (!text) {
      // Clear everything
      targetTextRef.current = ''
      setDisplayedText('')
      if (typewriterTimerRef.current) {
        clearInterval(typewriterTimerRef.current)
        typewriterTimerRef.current = null
      }
      return
    }
    targetTextRef.current = text
    // Start typewriter if not already running
    if (!typewriterTimerRef.current) {
      typewriterTimerRef.current = setInterval(() => {
        setDisplayedText(prev => {
          const target = targetTextRef.current
          if (prev.length >= target.length) {
            // Caught up — stop timer
            if (typewriterTimerRef.current) {
              clearInterval(typewriterTimerRef.current)
              typewriterTimerRef.current = null
            }
            return target
          }
          // Reveal 2-4 characters per tick for natural speed
          const charsToAdd = Math.min(3, target.length - prev.length)
          return target.substring(0, prev.length + charsToAdd)
        })
      }, 20) // ~50fps, 3 chars per tick ≈ 150 chars/sec
    }
  }, [])

  // Files
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  // New session
  const [showNewSession, setShowNewSession] = useState(false)
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [agentsLoading, setAgentsLoading] = useState(false)
  const [defaultAgentId, setDefaultAgentId] = useState('')
  const [slashCommands, setSlashCommands] = useState<SlashCommandItem[]>(buildSlashCommandItems([]))
  const [slashActiveIndex, setSlashActiveIndex] = useState(0)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const activeSessionKeyRef = useRef<string | null>(null)
  const slashMenuRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  const getAgentDisplayName = useCallback((agentId: string) => {
    const agent = agents.find(item => item.id === agentId)
    if (!agent) return agentId
    return agent.identity?.name || agent.name || agent.id
  }, [agents])

  const loadAgentsCatalog = useCallback(async () => {
    try {
      const result = await listAgents()
      setAgents(result.agents || [])
      setDefaultAgentId(result.defaultId || '')
    } catch {
      setAgents([])
    }
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, displayedText, scrollToBottom])

  // Load sessions
  const fetchSessions = useCallback(async () => {
    setSessionsLoading(true)
    try {
      const result = await listSessions()
      setSessions(result)
    } catch {
      setSessions([])
    } finally {
      setSessionsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  useEffect(() => {
    loadAgentsCatalog()
  }, [loadAgentsCatalog])

  useEffect(() => {
    let cancelled = false
    const agentId = activeSessionKey ? getAgentIdFromKey(activeSessionKey) : undefined

    const fetchSlashCommands = async () => {
      try {
        const result = await listSlashCommands(agentId)
        if (!cancelled) {
          setSlashCommands(buildSlashCommandItems(result.commands || []))
        }
      } catch {
        if (!cancelled) {
          setSlashCommands([])
        }
      }
    }

    fetchSlashCommands()
    return () => {
      cancelled = true
    }
  }, [activeSessionKey])

  // Restore session from URL param
  useEffect(() => {
    const sessionKey = searchParams.get('session')
    if (sessionKey && sessionKey !== activeSessionKey) {
      loadSession(sessionKey)
    }
  }, [searchParams])

  const loadSession = async (key: string) => {
    setActiveSessionKey(key)
    activeSessionKeyRef.current = key
    setChatLoading(true)
    setError('')
    setAgentRunning(false)
    setPendingFiles([])
    setSearchParams({ session: key })
    try {
      const detail = await getSession(key)
      setMessages(detail.messages || [])
    } catch (err: any) {
      setError(err?.message || '加载会话失败')
      setMessages([])
    } finally {
      setChatLoading(false)
    }
  }

  const handleDeleteSession = async (key: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('确定删除这个会话？')) return
    try {
      await deleteSession(key)
      setSessions(prev => prev.filter(s => s.key !== key))
      if (activeSessionKey === key) {
        setActiveSessionKey(null)
        activeSessionKeyRef.current = null
        setMessages([])
        setSearchParams({})
      }
    } catch {
      // ignore
    }
  }

  const handleStartRename = (session: Session, e: React.MouseEvent) => {
    e.stopPropagation()
    setRenamingSessionKey(session.key)
    setRenameValue(session.title || '')
  }

  const handleCancelRename = useCallback(() => {
    setRenamingSessionKey(null)
    setRenameValue('')
    setRenameSaving(false)
  }, [])

  const handleSaveRename = useCallback(async (key: string) => {
    if (renameSaving) return
    setRenameSaving(true)
    try {
      await updateSessionTitle(key, renameValue)
      await fetchSessions()
      handleCancelRename()
    } catch (err: any) {
      setError(err?.message || '重命名失败')
      setRenameSaving(false)
    }
  }, [fetchSessions, handleCancelRename, renameSaving, renameValue])

  const handleNewSession = async () => {
    setShowNewSession(true)
    setAgentsLoading(true)
    try {
      await loadAgentsCatalog()
    } catch {
      setAgents([])
    } finally {
      setAgentsLoading(false)
    }
  }

  const startNewSession = (agentId: string) => {
    const key = `agent:${agentId}:session-${Date.now()}`
    setActiveSessionKey(key)
    activeSessionKeyRef.current = key
    setMessages([])
    setPendingFiles([])
    setShowNewSession(false)
    setError('')
    setSearchParams({ session: key })
    setTimeout(() => inputRef.current?.focus(), 100)
  }

  // File handling
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return
    addFiles(Array.from(files))
    e.target.value = ''
  }

  const addFiles = (files: File[]) => {
    const newPending: PendingFile[] = files.map(file => {
      const isImg = isImageFile(file)
      const pf: PendingFile = {
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        file,
        name: file.name,
        isImage: isImg,
      }
      if (isImg) {
        pf.previewUrl = URL.createObjectURL(file)
      }
      return pf
    })
    setPendingFiles(prev => [...prev, ...newPending])
  }

  const removePendingFile = (id: string) => {
    setPendingFiles(prev => {
      const removed = prev.find(f => f.id === id)
      if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl)
      return prev.filter(f => f.id !== id)
    })
  }

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items) return
    const imageFiles: File[] = []
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        const file = items[i].getAsFile()
        if (file) imageFiles.push(file)
      }
    }
    if (imageFiles.length > 0) {
      addFiles(imageFiles)
    }
  }

  // Send message — upload all files to agent workspace first
  const handleSend = async () => {
    const text = input.trim()
    if ((!text && pendingFiles.length === 0) || !activeSessionKey || sending) return

    setSending(true)
    setError('')

    try {
      const agentId = getAgentIdFromKey(activeSessionKey)
      const uploadDir = getUploadDir(agentId)

      // Upload all files to agent workspace
      const uploadedPaths: string[] = []
      for (const pf of pendingFiles) {
        const result = await uploadFileToWorkspace(pf.file, uploadDir)
        uploadedPaths.push(result.path)
      }

      // Build final message with file references
      let finalMessage = text
      if (uploadedPaths.length > 0) {
        const fileRefs = uploadedPaths
          .map(p => `[附件: /opt/data/${p}]`)
          .join('\n')
        finalMessage = finalMessage
          ? `${finalMessage}\n\n${fileRefs}`
          : fileRefs
      }

      // Optimistic UI
      const displayParts: string[] = []
      if (text) displayParts.push(text)
      if (uploadedPaths.length > 0) {
        uploadedPaths.forEach(p => {
          const name = p.split('/').pop() || p
          displayParts.push(`📎 ${name}`)
        })
      }

      const userMsg = {
        role: 'user',
        content: displayParts.join('\n'),
        timestamp: new Date().toISOString(),
      }
      setMessages(prev => [...prev, userMsg])
      setInput('')
      pendingFiles.forEach(pf => {
        if (pf.previewUrl) URL.revokeObjectURL(pf.previewUrl)
      })
      setPendingFiles([])

      setStreamingText('')
      const baselineAssistantCount = messages.filter(msg => msg.role === 'assistant').length
      registerPendingSession(activeSessionKey, baselineAssistantCount)
      const sendResult = await sendChatMessage(activeSessionKey, finalMessage)

      // Auto-set session title from first user message
      if (messages.length === 0 && text) {
        const autoTitle = text.replace(/\n/g, ' ').slice(0, 50)
        updateSessionTitle(activeSessionKey, autoTitle).catch(() => {})
      }

      // Wait for response completion by runId; SSE still handles incremental text.
      await waitForResponse(activeSessionKey, sendResult.runId)
      fetchSessions()
    } catch (err: any) {
      if (activeSessionKey) clearPendingSession(activeSessionKey)
      setError(err?.message || '发送失败')
    } finally {
      setSending(false)
    }
  }

  // SSE connection for real-time chat events (replaces WebSocket)
  const runSseRef = useRef<EventSource | null>(null)
  const sseCompletedRef = useRef(false)
  const streamRunEvents = useCallback((key: string, runId: string) => {
    return new Promise<void>((resolve, reject) => {
      if (runSseRef.current) {
        runSseRef.current.close()
        runSseRef.current = null
      }

      let accumulated = ''
      let settled = false
      const sse = new EventSource(getRunEventsStreamUrl(runId))
      runSseRef.current = sse

      const closeStream = () => {
        sse.close()
        if (runSseRef.current === sse) {
          runSseRef.current = null
        }
      }

      const finish = (fn: () => void) => {
        if (settled) return
        settled = true
        closeStream()
        fn()
      }

      const sessionMatches = (sessionKey: string | null | undefined) => {
        if (!sessionKey) return true
        const currentKey = activeSessionKeyRef.current
        if (!currentKey) return false
        const normalizedGw = sessionKey.replace(/:/g, '')
        const normalizedActive = currentKey.replace(/:/g, '')
        return normalizedGw === normalizedActive || sessionKey === currentKey
      }

      sse.onmessage = (evt) => {
        try {
          const payload = JSON.parse(evt.data)
          const eventType = String(payload.type || payload.event || '')
          const sessionKey = typeof payload.session_id === 'string' ? payload.session_id : key

          if (!sessionMatches(sessionKey)) {
            return
          }

          if (eventType === 'message.delta') {
            const delta = typeof payload.delta === 'string' ? payload.delta : ''
            if (!delta) return
            accumulated += delta
            setStreamingText(accumulated)
            setAgentRunning(true)
            return
          }

          if (eventType === 'message.completed') {
            const content = payload.message?.content
            if (typeof content === 'string') {
              accumulated = content
              setStreamingText(accumulated)
            }
            return
          }

          if (eventType === 'tool.started') {
            const toolName = String(payload.tool || 'unknown')
            const toolId = `live-${Date.now()}-${toolName}`
            setLiveToolCalls(prev => [...prev, {
              id: toolId,
              tool: toolName,
              preview: typeof payload.preview === 'string' ? payload.preview : undefined,
              status: 'running',
            }])
            setAgentRunning(true)
            return
          }

          if (eventType === 'tool.completed') {
            const toolName = String(payload.tool || 'unknown')
            setLiveToolCalls(prev => {
              // Find the last running tool with this name and mark it done/error
              const idx = [...prev].reverse().findIndex(t => t.tool === toolName && t.status === 'running')
              if (idx === -1) return prev
              const realIdx = prev.length - 1 - idx
              const updated = [...prev]
              updated[realIdx] = {
                ...updated[realIdx],
                status: payload.error ? 'error' : 'done',
                duration: typeof payload.duration === 'number' ? payload.duration : undefined,
              }
              return updated
            })
            return
          }

          if (eventType === 'reasoning.available') {
            const text = typeof payload.text === 'string' ? payload.text : ''
            if (text) {
              setLiveReasoning(prev => prev ? prev + '\n' + text : text)
            }
            return
          }

          if (eventType === 'run.completed') {
            finish(() => {
              getSession(key).then(detail => {
                setMessages(detail.messages || [])
                setStreamingText('')
                setLiveToolCalls([])
                setLiveReasoning('')
                setSending(false)
                setAgentRunning(false)
                sseCompletedRef.current = true
                fetchSessions()
                resolve()
              }).catch((err) => {
                setStreamingText('')
                setLiveToolCalls([])
                setLiveReasoning('')
                setSending(false)
                setAgentRunning(false)
                sseCompletedRef.current = true
                reject(err)
              })
            })
            return
          }

          if (eventType === 'run.failed') {
            finish(() => {
              setStreamingText('')
              setLiveToolCalls([])
              setLiveReasoning('')
              setSending(false)
              setAgentRunning(false)
              sseCompletedRef.current = true
              reject(new Error(String(payload.error || 'run failed')))
            })
          }
        } catch {
          // ignore malformed chunks
        }
      }

      sse.onerror = () => {
        finish(() => {
          reject(new Error('run event stream disconnected'))
        })
      }
    })
  }, [fetchSessions, getRunEventsStreamUrl, setStreamingText])

  useEffect(() => {
    return () => {
      if (typewriterTimerRef.current) clearInterval(typewriterTimerRef.current)
      if (runSseRef.current) {
        runSseRef.current.close()
        runSseRef.current = null
      }
    }
  }, [])

  const waitForResponse = async (key: string, runId: string | null) => {
    sseCompletedRef.current = false
    if (runId) {
      try {
        await streamRunEvents(key, runId)
        return
      } catch {
        if (key !== activeSessionKeyRef.current) return
      }
    }

    const maxWaitMs = 240000 // 4 minutes max
    const perRequestTimeoutMs = 25000
    const startTime = Date.now()

    while (Date.now() - startTime < maxWaitMs) {
      if (sseCompletedRef.current) return
      if (key !== activeSessionKeyRef.current) return

      if (runId) {
        try {
          const remainingMs = maxWaitMs - (Date.now() - startTime)
          const waitResult = await waitForAgentRun(runId, Math.min(perRequestTimeoutMs, remainingMs))

          if (sseCompletedRef.current) return
          if (key !== activeSessionKeyRef.current) return

          if (waitResult.status === 'timeout') {
            continue
          }

          const detail = await getSession(key)
          setMessages(detail.messages || [])
          setStreamingText('')
          sseCompletedRef.current = true
          return
        } catch {
          await new Promise(r => setTimeout(r, 1500))
          continue
        }
      }

      // Legacy fallback if backend doesn't return a runId.
      await new Promise(r => setTimeout(r, 3000))
      try {
        const detail = await getSession(key)
        const msgs = detail.messages || []
        const lastMsg = msgs[msgs.length - 1]
        if (lastMsg?.role === 'assistant' && !targetTextRef.current) {
          setMessages(msgs)
          setStreamingText('')
          sseCompletedRef.current = true
          return
        }
      } catch {
        // ignore and keep waiting
      }
    }

    // Timeout — load final state
    try {
      const detail = await getSession(key)
      setMessages(detail.messages || [])
    } catch {}
    setStreamingText('')
    setAgentRunning(false)
    sseCompletedRef.current = true
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (showSlashMenu && filteredSlashCommands.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSlashActiveIndex(prev => (prev + 1) % filteredSlashCommands.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSlashActiveIndex(prev => (prev - 1 + filteredSlashCommands.length) % filteredSlashCommands.length)
        return
      }
      if ((e.key === 'Enter' || e.key === 'Tab') && !e.nativeEvent.isComposing) {
        e.preventDefault()
        applySlashCommand(filteredSlashCommands[slashActiveIndex] || filteredSlashCommands[0])
        return
      }
    }
    if (showSlashMenu && e.key === 'Escape') {
      e.preventDefault()
      setSlashActiveIndex(0)
      return
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleRefresh = () => {
    if (activeSessionKey) {
      loadSession(activeSessionKey)
    }
  }

  const formatTime = (iso: string | null) => {
    if (!iso) return ''
    const d = new Date(iso)
    const now = new Date()
    const isToday = d.toDateString() === now.toDateString()
    const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    if (isToday) return time
    return `${d.getMonth() + 1}/${d.getDate()} ${time}`
  }

  const hasContent = input.trim() || pendingFiles.length > 0
  const slashQuery = getSlashQuery(input)
  const filteredSlashCommands = filterSlashCommands(slashCommands, slashQuery || '')
  const showSlashMenu = Boolean(activeSessionKey && slashQuery !== null)
  const groupedSlashCommands = filteredSlashCommands.reduce<Record<string, SlashCommandItem[]>>((acc, command) => {
    const key = command.category
    if (!acc[key]) acc[key] = []
    acc[key].push(command)
    return acc
  }, {})

  useEffect(() => {
    setSlashActiveIndex(0)
  }, [slashQuery])

  useEffect(() => {
    if (!showSlashMenu || filteredSlashCommands.length === 0) return
    if (slashActiveIndex >= filteredSlashCommands.length) {
      setSlashActiveIndex(0)
    }
  }, [showSlashMenu, filteredSlashCommands, slashActiveIndex])

  useEffect(() => {
    if (!showSlashMenu) return
    const activeButton = slashMenuRef.current?.querySelector<HTMLButtonElement>('[data-active="true"]')
    activeButton?.scrollIntoView({ block: 'nearest' })
  }, [showSlashMenu, slashActiveIndex])

  const applySlashCommand = (command: SlashCommandItem) => {
    setInput(`/${command.name} `)
    setSlashActiveIndex(0)
    setTimeout(() => {
      inputRef.current?.focus()
    }, 0)
  }

  return (
    <div className="flex h-[calc(100vh-3rem)] -m-6">
      {/* Session sidebar */}
      <div className="w-64 border-r border-dark-border bg-dark-sidebar flex flex-col shrink-0">
        <div className="px-4 py-3 border-b border-dark-border flex items-center justify-between">
          <h2 className="text-sm font-semibold text-dark-text">会话</h2>
          <button
            onClick={handleNewSession}
            className="flex items-center gap-1 rounded-lg bg-accent-blue px-2.5 py-1 text-xs font-medium text-white hover:bg-accent-blue/90 transition-colors"
          >
            <Plus size={12} />
            新建
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {sessionsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={18} className="animate-spin text-accent-blue" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="px-4 py-8 text-center text-xs text-dark-text-secondary">
              暂无会话
            </div>
          ) : (
            <div className="py-1">
              {sessions.map(s => {
                const isRenaming = renamingSessionKey === s.key
                const isActive = activeSessionKey === s.key

                return (
                  <div
                    key={s.key}
                    className={`group flex items-center gap-2 px-3 py-2.5 transition-colors ${
                      isActive
                        ? 'bg-accent-blue/10 text-accent-blue'
                        : 'text-dark-text-secondary hover:bg-dark-card hover:text-dark-text'
                    }`}
                  >
                    <button
                      onClick={() => !isRenaming && loadSession(s.key)}
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      disabled={isRenaming}
                    >
                      <MessageSquare size={14} className="shrink-0" />
                      <div className="flex-1 min-w-0">
                        {isRenaming ? (
                          <input
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onClick={(e) => e.stopPropagation()}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault()
                                void handleSaveRename(s.key)
                              } else if (e.key === 'Escape') {
                                e.preventDefault()
                                handleCancelRename()
                              }
                            }}
                            className="w-full rounded border border-accent-blue/40 bg-dark-bg px-2 py-1 text-xs font-medium text-dark-text outline-none focus:border-accent-blue"
                            placeholder="输入会话标题"
                            autoFocus
                          />
                        ) : (
                          <div className="text-xs font-medium truncate">
                            {s.title || s.key}
                          </div>
                        )}
                        <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-dark-text-secondary">
                          <span>{formatTime(s.updated_at)}</span>
                          <span className="rounded-full border border-dark-border bg-dark-bg/80 px-1.5 py-0.5 text-[9px] font-medium text-dark-text-secondary">
                            {getAgentDisplayName(getAgentIdFromKey(s.key))}
                          </span>
                        </div>
                      </div>
                    </button>

                    <div className="flex shrink-0 items-center gap-1">
                      {isRenaming ? (
                        <>
                          <button
                            onClick={() => void handleSaveRename(s.key)}
                            className="text-dark-text-secondary hover:text-accent-blue transition-colors"
                            title="保存标题"
                            disabled={renameSaving}
                          >
                            {renameSaving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                          </button>
                          <button
                            onClick={handleCancelRename}
                            className="text-dark-text-secondary hover:text-dark-text transition-colors"
                            title="取消"
                            disabled={renameSaving}
                          >
                            <X size={12} />
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={(e) => handleStartRename(s, e)}
                            className="opacity-0 group-hover:opacity-100 text-dark-text-secondary hover:text-dark-text transition-all"
                            title="重命名"
                          >
                            <Pencil size={12} />
                          </button>
                          <button
                            onClick={(e) => handleDeleteSession(s.key, e)}
                            className="opacity-0 group-hover:opacity-100 text-dark-text-secondary hover:text-accent-red transition-all"
                            title="删除"
                          >
                            <Trash2 size={12} />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {activeSessionKey ? (
          <>
            {/* Chat header */}
            <div className="px-5 py-3 border-b border-dark-border flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <Bot size={16} className="text-accent-blue shrink-0" />
                <span className="text-sm font-medium text-dark-text truncate">
                  {getAgentIdFromKey(activeSessionKey)}
                </span>
                <ChevronRight size={12} className="text-dark-text-secondary shrink-0" />
                <span className="text-xs text-dark-text-secondary truncate">
                  {activeSessionKey.split(':').pop()}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {(sending || agentRunning) && (
                  <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-accent-blue/10 border border-accent-blue/20 animate-pulse">
                    <Loader2 size={12} className="animate-spin text-accent-blue" />
                    <span className="text-[11px] text-accent-blue font-medium">处理中</span>
                  </div>
                )}
                <button
                  onClick={handleRefresh}
                  className="text-dark-text-secondary hover:text-dark-text transition-colors"
                  title="刷新"
                >
                  <RefreshCw size={14} />
                </button>
              </div>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {chatLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 size={24} className="animate-spin text-accent-blue" />
                </div>
              ) : messages.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-20 text-dark-text-secondary">
                  <MessageSquare size={40} className="mb-3 opacity-30" />
                  <p className="text-sm">发送消息开始对话</p>
                  <p className="text-xs mt-1 opacity-60">支持上传图片和文件附件</p>
                </div>
              ) : (
                <div className="space-y-4 max-w-3xl mx-auto">
                  {groupToolCalls(messages as ChatMessage[]).map((item, i) => {
                    // Tool call group → collapsible card
                    if ('assistant' in item && 'toolResults' in item) {
                      const group = item as ToolCallGroup
                      return (
                        <div key={`tc-${i}`} className="flex gap-3">
                          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-blue/10 text-accent-blue mt-0.5">
                            <Bot size={14} />
                          </div>
                          <div className="flex-1 max-w-[80%]">
                            <ToolCallGroupCard group={group} />
                          </div>
                        </div>
                      )
                    }

                    const msg = item as ChatMessage
                    return (
                      <div
                        key={i}
                        className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : ''}`}
                      >
                        {msg.role !== 'user' && (
                          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-blue/10 text-accent-blue mt-0.5">
                            <Bot size={14} />
                          </div>
                        )}
                        <div className="flex flex-col items-start max-w-[80%]">
                          {/* Thinking / reasoning collapsible card */}
                          {msg.role === 'assistant' && (msg._thinking || msg.reasoning_content) && (
                            <ThinkingCard content={(msg._thinking || msg.reasoning_content)!} />
                          )}
                          {/* Main message bubble */}
                          {msg.content?.trim() && (
                            <div
                              className={`rounded-xl px-4 py-2.5 w-full ${
                                msg.role === 'user'
                                  ? 'bg-accent-blue text-white'
                                  : 'bg-dark-card border border-dark-border text-dark-text'
                              }`}
                            >
                              {msg.role === 'user' ? (
                                <div className="text-sm whitespace-pre-wrap break-words">{msg.content}</div>
                              ) : (
                                <MarkdownContent content={msg.content} />
                              )}
                              {msg.timestamp && (
                                <div className={`text-[10px] mt-1 ${
                                  msg.role === 'user' ? 'text-white/60' : 'text-dark-text-secondary'
                                }`}>
                                  {formatTime(msg.timestamp)}
                                </div>
                              )}
                            </div>
                          )}
                          {msg.role !== 'user' && msg.content?.trim() && (
                            <button
                              onClick={() => {
                                navigator.clipboard.writeText(msg.content)
                                setCopiedIdx(i)
                                setTimeout(() => setCopiedIdx(null), 2000)
                              }}
                              className="flex items-center gap-1 mt-1 px-2 py-0.5 text-[11px] text-dark-text-secondary hover:text-dark-text rounded transition-colors"
                            >
                              {copiedIdx === i ? <><Check size={12} /> 已复制</> : <><Copy size={12} /> 复制</>}
                            </button>
                          )}
                        </div>
                        {msg.role === 'user' && (
                          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-purple/10 text-accent-purple mt-0.5">
                            <User size={14} />
                          </div>
                        )}
                      </div>
                    )
                  })}
                  {sending && (
                    <div className="flex gap-3">
                      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-blue/10 text-accent-blue mt-0.5">
                        <Bot size={14} />
                      </div>
                      <div className="flex-1 max-w-[80%]">
                        {/* Live reasoning */}
                        {liveReasoning && (
                          <LiveReasoningCard content={liveReasoning} />
                        )}
                        {/* Live tool calls */}
                        {liveToolCalls.length > 0 && (
                          <LiveToolCallsCard tools={liveToolCalls} />
                        )}
                        {/* Streaming text bubble */}
                        <div className="rounded-xl px-4 py-2.5 bg-dark-card border border-dark-border">
                          {displayedText ? (
                            <div className="text-dark-text">
                              <MarkdownContent content={displayedText} />
                              <span className="inline-block w-1.5 h-4 ml-0.5 bg-accent-blue rounded-sm animate-pulse align-text-bottom" />
                            </div>
                          ) : (
                            <div className="flex items-center gap-2 text-sm text-dark-text-secondary">
                              <Loader2 size={14} className="animate-spin" />
                              {liveToolCalls.some(t => t.status === 'running') ? '工具执行中...' : '思考中...'}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                  <div ref={messagesEndRef} />
                </div>
              )}
            </div>

            {/* Error */}
            {error && (
              <div className="px-5 py-2">
                <div className="rounded-lg bg-accent-red/10 px-3 py-2 text-xs text-accent-red max-w-3xl mx-auto">
                  {error}
                </div>
              </div>
            )}

            {/* Pending files preview */}
            {pendingFiles.length > 0 && (
              <div className="px-5 pt-2 shrink-0">
                <div className="max-w-3xl mx-auto flex flex-wrap gap-2">
                  {pendingFiles.map(pf => (
                    <div
                      key={pf.id}
                      className="relative group rounded-lg border border-dark-border bg-dark-card overflow-hidden"
                    >
                      {pf.isImage && pf.previewUrl ? (
                        <div className="relative">
                          <img
                            src={pf.previewUrl}
                            alt={pf.name}
                            className="h-16 w-16 object-cover"
                          />
                          <div className="absolute bottom-0 left-0 right-0 bg-black/50 px-1 py-0.5">
                            <div className="text-[9px] text-white truncate">{pf.name}</div>
                          </div>
                        </div>
                      ) : (
                        <div className="h-16 w-auto flex items-center gap-2 px-3">
                          <FileText size={16} className="text-accent-blue shrink-0" />
                          <div className="min-w-0">
                            <div className="text-xs text-dark-text truncate max-w-[120px]">{pf.name}</div>
                            <div className="text-[10px] text-dark-text-secondary">{formatFileSize(pf.file.size)}</div>
                          </div>
                        </div>
                      )}
                      <button
                        onClick={() => removePendingFile(pf.id)}
                        className="absolute top-0.5 right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-black/60 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        <X size={10} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Input */}
            <div className="px-5 py-3 border-t border-dark-border shrink-0">
              <div className="max-w-3xl mx-auto flex items-end gap-2">
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={sending}
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-dark-border text-dark-text-secondary hover:text-accent-blue hover:border-accent-blue/30 transition-colors disabled:opacity-50"
                  title="上传附件（图片/文件）"
                >
                  <Paperclip size={16} />
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  onChange={handleFileSelect}
                  className="hidden"
                />
                <div className="relative flex-1">
                  {showSlashMenu && (
                    <div
                      ref={slashMenuRef}
                      className="absolute bottom-full left-0 right-0 mb-2 max-h-72 overflow-y-auto rounded-2xl border border-dark-border bg-dark-card shadow-2xl"
                    >
                      {filteredSlashCommands.length === 0 ? (
                        <div className="px-4 py-3 text-sm text-dark-text-secondary">
                          没有匹配的斜杠命令
                        </div>
                      ) : (
                        Object.entries(groupedSlashCommands).map(([category, commands]) => (
                          <div key={category} className="border-b border-dark-border/60 last:border-b-0">
                            <div className="px-4 pt-3 pb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-dark-text-secondary">
                              {CATEGORY_LABELS[category as keyof typeof CATEGORY_LABELS]}
                            </div>
                            <div className="pb-2">
                              {commands.map(command => {
                                const index = filteredSlashCommands.findIndex(item => item.name === command.name)
                                const isActive = index === slashActiveIndex
                                return (
                                  <button
                                    key={`${command.source}-${command.name}`}
                                    type="button"
                                    data-active={isActive ? 'true' : 'false'}
                                    onMouseEnter={() => setSlashActiveIndex(index)}
                                    onClick={() => applySlashCommand(command)}
                                    className={`flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors ${
                                      isActive ? 'bg-accent-blue/12' : 'hover:bg-dark-card-hover'
                                    }`}
                                  >
                                    <div className={`mt-0.5 rounded-md px-2 py-1 text-[11px] font-semibold ${
                                      command.source === 'skill'
                                        ? 'bg-accent-purple/12 text-accent-purple'
                                        : 'bg-accent-blue/12 text-accent-blue'
                                    }`}>
                                      /
                                    </div>
                                    <div className="min-w-0 flex-1">
                                      <div className="flex items-center gap-2">
                                        <span className={`text-sm font-medium ${isActive ? 'text-accent-blue' : 'text-dark-text'}`}>
                                          /{command.name}
                                        </span>
                                        {command.argsHint && (
                                          <span className="truncate text-xs text-dark-text-secondary">
                                            {command.argsHint}
                                          </span>
                                        )}
                                      </div>
                                      <div className="mt-0.5 text-xs text-dark-text-secondary">
                                        {command.description}
                                      </div>
                                    </div>
                                  </button>
                                )
                              })}
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                  <textarea
                    ref={inputRef}
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onPaste={handlePaste}
                    placeholder={pendingFiles.length > 0 ? '添加说明（可选）...' : '输入消息，可粘贴图片，输入 / 可选命令...'}
                    rows={1}
                    className="flex-1 w-full rounded-xl border border-dark-border bg-dark-card px-4 py-2.5 text-sm text-dark-text outline-none focus:border-accent-blue placeholder:text-dark-text-secondary resize-none max-h-32"
                    style={{ minHeight: '40px' }}
                    disabled={sending}
                  />
                </div>
                <button
                  onClick={handleSend}
                  disabled={!hasContent || sending}
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-blue text-white hover:bg-accent-blue/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                </button>
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-dark-text-secondary">
            <MessageSquare size={48} className="mb-4 opacity-20" />
            <p className="text-sm mb-4">选择一个会话或创建新会话</p>
            <button
              onClick={handleNewSession}
              className="flex items-center gap-2 rounded-lg bg-accent-blue px-4 py-2 text-sm font-medium text-white hover:bg-accent-blue/90 transition-colors"
            >
              <Plus size={16} />
              新建会话
            </button>
          </div>
        )}
      </div>

      {/* New session modal */}
      {showNewSession && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="rounded-xl bg-dark-card border border-dark-border max-w-md w-full mx-4 shadow-xl">
            <div className="flex items-center justify-between px-5 py-4 border-b border-dark-border">
              <h3 className="text-base font-semibold text-dark-text">选择 Agent</h3>
              <button
                onClick={() => setShowNewSession(false)}
                className="text-dark-text-secondary hover:text-dark-text transition-colors text-lg"
              >
                ×
              </button>
            </div>
            <div className="px-5 py-4">
              {agentsLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 size={24} className="animate-spin text-accent-blue" />
                </div>
              ) : agents.length === 0 ? (
                <div className="text-center py-8 text-sm text-dark-text-secondary">
                  暂无可用 Agent
                </div>
              ) : (
                <div className="space-y-2 max-h-80 overflow-y-auto">
                  {agents.map(agent => (
                    <button
                      key={agent.id}
                      onClick={() => startNewSession(agent.id)}
                      className="w-full flex items-center gap-3 rounded-xl border border-dark-border p-3 text-left hover:bg-dark-bg/50 hover:border-accent-blue/30 transition-colors group"
                    >
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-blue/10 text-lg">
                        {agent.identity?.emoji || '🤖'}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-dark-text truncate">
                            {agent.identity?.name || agent.name || agent.id}
                          </span>
                          {agent.id === defaultAgentId && (
                            <span className="rounded-full bg-accent-blue/10 px-2 py-0.5 text-[10px] text-accent-blue font-medium shrink-0">
                              默认
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-dark-text-secondary truncate mt-0.5">
                          {agent.id}
                        </div>
                      </div>
                      <ChevronRight size={14} className="text-dark-text-secondary opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
