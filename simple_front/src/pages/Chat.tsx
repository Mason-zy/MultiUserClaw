import { useState, useEffect, useRef, useCallback, useMemo, type CSSProperties } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'
import {
  Plus,
  Send,
  Loader2,
  MessageSquare,
  Bot,
  Search,
  RefreshCw,
  ChevronDown,
  Copy,
  Check,
  X,
  FileText,
  Menu,
  Square,
  ChevronRight,
  Wrench,
  Brain,
  CircleCheck,
  AlertCircle,
  ShieldQuestion,
} from 'lucide-react'
import MarkdownContent from '../components/MarkdownContent.tsx'
import AgentCreatePanel from '../components/AgentCreatePanel.tsx'
import ClearableInput from '../components/ui/ClearableInput.tsx'
import ClearableTextarea from '../components/ui/ClearableTextarea.tsx'
import IconButton from '../components/ui/IconButton.tsx'
import Tooltip from '../components/ui/Tooltip.tsx'
import { useToast } from '../components/ui/Toast.tsx'
import type { LayoutOutletContext } from '../components/Layout.tsx'
import {
  getSession,
  sendChatMessage,
  waitForAgentRun,
  getRunEventsStreamUrl,
  abortAgentRun,
  abortActiveSessionRun,
  respondRunApproval,
  getAccessToken,
  uploadFileToWorkspace,
  generateSessionTitle,
  listSlashCommands,
  listModels,
} from '../lib/api.ts'
import type { Session, SessionDetail, AgentInfo, ModelChoice } from '../lib/api.ts'
import {
  CATEGORY_LABELS,
  CATEGORY_STYLES,
  buildSlashCommandItems,
  filterSlashCommands,
  getSlashQuery,
  type SlashCommandItem,
} from '../lib/slashCommands.ts'

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
 * Hermes profiles keep uploads under profiles/<agentId>/workspace/uploads.
 */
function getUploadDir(agentId: string): string {
  return 'profiles/' + agentId + '/workspace/uploads'
}

interface PendingFile {
  id: string
  file: File
  name: string
  isImage: boolean
  previewUrl?: string
}

type AgentActivityStatus = 'running' | 'completed' | 'failed' | 'thinking' | 'approval'
type RunStreamResult = 'completed' | 'failed' | 'cancelled' | 'error'

interface AgentActivityEvent {
  id: string
  runId: string
  type: string
  title: string
  detail?: string
  status: AgentActivityStatus
  timestamp: number
  choices?: string[]
  selectedChoice?: string
  responding?: boolean
}

interface AgentActivityArchive {
  id: string
  runId: string
  startedAt: number
  endedAt: number
  events: AgentActivityEvent[]
  expanded: boolean
  assistantIndex?: number
  thoughts?: string[]
  toolEventsExpanded?: boolean
  durationReliable?: boolean
}

interface RunActivityStream {
  ready: Promise<boolean>
  done: Promise<RunStreamResult>
}

function tryParseJSONObject(text: string): Record<string, unknown> | null {
  const trimmed = text.trim()
  if (!trimmed.startsWith('{') || !trimmed.endsWith('}')) return null
  try {
    const parsed = JSON.parse(trimmed)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null
  } catch {
    return null
  }
}

function isToolResultMessage(content: string): boolean {
  const parsed = tryParseJSONObject(content)
  if (!parsed) return false
  const keys = Object.keys(parsed)
  return (
    ('output' in parsed && ('exit_code' in parsed || 'approval' in parsed || 'error' in parsed)) ||
    (keys.length <= 5 && 'exit_code' in parsed && ('stdout' in parsed || 'stderr' in parsed))
  )
}

function isProcessingPreludeMessage(content: string): boolean {
  const normalized = content.trim().replace(/\s+/g, ' ').toLowerCase()
  if (!normalized) return true
  return [
    'let me check',
    "i'll check",
    'i will check',
    "i'm going to check",
    'i am going to check',
    'checking ',
    'checking',
    'checking now',
    'let me check',
    'i will check',
    'check first',
    'check',
  ].some(prefix => normalized.startsWith(prefix))
}

function isVisibleChatMessage(messages: SessionDetail['messages'], index: number): boolean {
  const msg = messages[index]
  if (!msg) return false
  if (msg.role !== 'user' && msg.role !== 'assistant') return false
  if (msg.role === 'assistant' && !(msg.content || '').trim()) return false
  if (msg.role === 'assistant' && isProcessingPreludeMessage(msg.content || '')) {
    const followedByTool = messages.slice(index + 1).some(next => {
      if (next.role === 'user') return false
      return next.role === 'tool'
    })
    if (followedByTool) return false
  }
  return !(msg.role === 'assistant' && isToolResultMessage(msg.content || ''))
}

function filterVisibleMessages(messages: SessionDetail['messages']): SessionDetail['messages'] {
  return messages.filter((_, index) => isVisibleChatMessage(messages, index))
}

function latestVisibleAssistantTurn(messages: SessionDetail['messages']): SessionDetail['messages'] {
  let assistantIndex = -1
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === 'assistant' && isVisibleChatMessage(messages, index)) {
      assistantIndex = index
      break
    }
  }
  if (assistantIndex < 0) return []

  let userIndex = -1
  for (let index = assistantIndex - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === 'user') {
      userIndex = index
      break
    }
  }
  return messages.slice(userIndex + 1, assistantIndex + 1)
}

function visibleAssistantCountBefore(messages: SessionDetail['messages'], rawAssistantIndex: number): number {
  let count = 0
  for (let index = 0; index <= rawAssistantIndex; index += 1) {
    if (messages[index]?.role === 'assistant' && isVisibleChatMessage(messages, index)) {
      count += 1
    }
  }
  return count
}

function latestVisibleAssistantIndex(messages: SessionDetail['messages']): number | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === 'assistant' && isVisibleChatMessage(messages, index)) {
      return visibleAssistantCountBefore(messages, index) - 1
    }
  }
  return undefined
}

function hasProcessingForLatestTurn(messages: SessionDetail['messages']): boolean {
  const turn = latestVisibleAssistantTurn(messages)
  return turn.some((msg, index) => {
    if (msg.role === 'tool') return true
    if (msg.role !== 'assistant') return false
    if (msg.role === 'assistant' && isProcessingPreludeMessage(msg.content || '')) {
      return turn.slice(index + 1).some(next => {
        if (next.role === 'user') return false
        return next.role === 'tool'
      })
    }
    return false
  })
}

function buildProcessingEvents(messages: SessionDetail['messages']): AgentActivityEvent[] {
  return messages.flatMap((msg, index) => {
    if (msg.role === 'tool') {
      const detail = (msg.content || '').trim()
      return [{
        id: 'history-tool:' + index,
        runId: '',
        type: 'tool.completed',
        title: '工具已完成',
        detail: detail.length > 420 ? detail.slice(0, 420) + '...' : detail,
        status: 'completed' as AgentActivityStatus,
        timestamp: Date.now(),
      }]
    }
    return []
  })
}

function extractProcessingThoughts(messages: SessionDetail['messages']): string[] {
  return messages.flatMap((msg, index) => {
    if (msg.role !== 'assistant' || !isProcessingPreludeMessage(msg.content || '')) return []
    const followedByTool = messages.slice(index + 1).some(next => {
      if (next.role === 'user') return false
      return next.role === 'tool'
    })
    return followedByTool ? [msg.content.trim()] : []
  })
}

function formatActivityDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes <= 0) return String(seconds) + 's'
  return String(minutes) + 'm ' + String(seconds) + 's'
}

function archiveStorageKey(sessionKey: string): string {
  return 'openclaw:activity-archives:' + sessionKey
}

function loadActivityArchives(sessionKey: string): AgentActivityArchive[] {
  try {
    const raw = window.sessionStorage.getItem(archiveStorageKey(sessionKey))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter(item => item && Array.isArray(item.events)) : []
  } catch {
    return []
  }
}

function saveActivityArchives(sessionKey: string, archives: AgentActivityArchive[]) {
  try {
    window.sessionStorage.setItem(archiveStorageKey(sessionKey), JSON.stringify(archives.slice(-6)))
  } catch {
    // Ignore storage quota/privacy mode errors; live state still works.
  }
}

function isImageFile(file: File): boolean {
  return file.type.startsWith('image/')
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return String(bytes) + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function normalizeSessionKey(key: string): string {
  return key.replace(/:/g, '')
}

function buildFallbackTitleFromText(fileCount = 0): string {
  if (fileCount > 0) return fileCount === 1 ? '处理附件' : '处理 ' + fileCount + ' 个附件'
  return '新对话'
}

function buildTitleFromMessages(messages: SessionDetail['messages']): string {
  const firstUserMessage = messages.find(msg => msg.role === 'user' && msg.content.trim())
  if (!firstUserMessage) return ''
  return buildFallbackTitleFromText()
}

function hasAssistantAfterLastUser(messages: SessionDetail['messages']): boolean {
  const visibleMessages = filterVisibleMessages(messages)
  const lastUserIndex = visibleMessages.map(msg => msg.role).lastIndexOf('user')
  if (lastUserIndex < 0) return visibleMessages.some(msg => msg.role === 'assistant' && msg.content.trim())
  return visibleMessages
    .slice(lastUserIndex + 1)
    .some(msg => msg.role === 'assistant' && msg.content.trim())
}

function isRunFinished(status: string | undefined): boolean {
  return ['ok', 'completed', 'error', 'failed', 'aborted', 'cancelled'].includes(status || '')
}

function isRunFailed(status: string | undefined): boolean {
  return ['error', 'failed'].includes(status || '')
}

function formatToolName(name: string): string {
  return name
    .replace(/^mcp__/, '')
    .replace(/__/g, ' / ')
    .replace(/[_-]+/g, ' ')
    .trim() || '未知工具'
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

function buildActivityTitle(eventType: string, payload: any): string {
  const upstreamTitle = firstString(payload.title, payload.label, payload.name)
  if (upstreamTitle) return upstreamTitle
  if (eventType === 'tool.started') {
    return '正在运行 ' + formatToolName(String(payload.tool || 'tool'))
  }
  if (eventType === 'tool.completed') {
    return (payload.error ? '工具执行失败' : '工具已完成') + ': ' + formatToolName(String(payload.tool || 'tool'))
  }
  if (eventType === 'reasoning.available') return '正在思考下一步'
  if (eventType === 'approval.request') return '等待授权'
  if (eventType === 'run.failed') return 'Agent 执行失败'
  return 'Agent 状态'
}

function buildActivityDetail(eventType: string, payload: any): string | undefined {
  const preview = firstString(payload.preview, payload.description, payload.command, payload.input)
  const text = firstString(payload.text, payload.summary)
  const error = firstString(payload.error, payload.message)
  if (eventType === 'tool.started') return preview || undefined
  if (eventType === 'tool.completed') {
    const duration = typeof payload.duration === 'number' ? payload.duration.toFixed(1) + 's' : ''
    return error || duration || undefined
  }
  if (eventType === 'reasoning.available') return text || preview || '正在分析任务并选择工具'
  if (eventType === 'approval.request') return preview || text || '需要授权后才能继续'
  if (eventType === 'run.failed') return error || undefined
  return preview || text || error || undefined
}

function normalizeApprovalChoices(payload: any): string[] {
  return Array.isArray(payload.choices)
    ? payload.choices.filter((choice: unknown): choice is string => typeof choice === 'string' && Boolean(choice.trim()))
    : []
}

function approvalChoiceLabel(choice: string): string {
  const labels: Record<string, string> = {
    once: '本次允许',
    session: '本会话允许',
    always: '始终允许',
    deny: '拒绝',
  }
  return labels[choice] || choice
}

const agentDescriptions: Record<string, string> = {
  main: '处理通用任务的默认助手',
  manager: '拆解任务并协调多个 Agent',
  programmer: '代码、工程、调试和技术方案',
  researcher: '检索公开信息并整理结论',
  hr: '招聘与人力流程助手',
  doctor: '医疗咨询场景的专业助手',
}

function ChatHistorySkeleton() {
  return (
    <div className="mx-auto max-w-4xl space-y-5 py-2" aria-label="正在加载对话历史">
      <div className="flex justify-end gap-3">
        <div className="flex w-full max-w-[64%] flex-col items-end gap-2">
          <div className="skeleton-shimmer h-11 w-full rounded-xl" />
          <div className="skeleton-shimmer h-2.5 w-16 rounded-full" />
        </div>
      </div>

      <div className="flex">
        <div className="w-full max-w-[78%] px-1 py-2">
          <div className="skeleton-shimmer h-3.5 w-11/12 rounded-full" />
          <div className="skeleton-shimmer mt-2.5 h-3.5 w-full rounded-full" />
          <div className="skeleton-shimmer mt-2.5 h-3.5 w-8/12 rounded-full" />
          <div className="skeleton-shimmer mt-3 h-2.5 w-14 rounded-full" />
        </div>
      </div>

      <div className="flex justify-end gap-3">
        <div className="flex w-full max-w-[52%] flex-col items-end gap-2">
          <div className="skeleton-shimmer h-10 w-full rounded-xl" />
          <div className="skeleton-shimmer h-2.5 w-14 rounded-full" />
        </div>
      </div>

      <div className="flex">
        <div className="w-full max-w-[72%] px-1 py-2">
          <div className="skeleton-shimmer h-3.5 w-full rounded-full" />
          <div className="skeleton-shimmer mt-2.5 h-3.5 w-9/12 rounded-full" />
          <div className="skeleton-shimmer mt-3 h-2.5 w-14 rounded-full" />
        </div>
      </div>
    </div>
  )
}

export default function Chat() {
  const [searchParams, setSearchParams] = useSearchParams()
  const {
    agents,
    currentSessionTitle,
    refreshAgents,
    refreshSessions,
    addOptimisticSession,
    setSessionThinking,
    openMobileSidebar,
  } = useOutletContext<LayoutOutletContext>()

  // Sessions
  const [activeSessionKey, setActiveSessionKey] = useState<string | null>(null)

  // Chat
  const [messages, setMessages] = useState<SessionDetail['messages']>([])
  const [chatLoading, setChatLoading] = useState(false)
  const [input, setInput] = useState('')
  const [slashCommands, setSlashCommands] = useState<SlashCommandItem[]>([])
  const [slashCommandsLoading, setSlashCommandsLoading] = useState(false)
  const [slashCommandsError, setSlashCommandsError] = useState('')
  const [slashActiveIndex, setSlashActiveIndex] = useState(0)
  const [slashMenuDismissed, setSlashMenuDismissed] = useState(false)
  const [sendingBySession, setSendingBySession] = useState<Record<string, boolean>>({})
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null)
  const [displayedTextBySession, setDisplayedTextBySession] = useState<Record<string, string>>({})
  const [activityBySession, setActivityBySession] = useState<Record<string, AgentActivityEvent[]>>({})
  const [activityArchivesBySession, setActivityArchivesBySession] = useState<Record<string, AgentActivityArchive[]>>({})
  const activityBySessionRef = useRef<Record<string, AgentActivityEvent[]>>({})
  const targetTextBySessionRef = useRef<Record<string, string>>({})
  const typewriterTimersRef = useRef<Record<string, ReturnType<typeof setInterval>>>({})
  const sendingBySessionRef = useRef<Record<string, boolean>>({})
  const runIdBySessionRef = useRef<Record<string, string>>({})
  const abortedSessionRef = useRef<Record<string, boolean>>({})
  const sseCompletedRef = useRef<Record<string, boolean>>({})
  const sseFinalTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const runEventSourcesRef = useRef<Record<string, EventSource>>({})
  const runStreamDoneRef = useRef<Record<string, RunStreamResult>>({})
  const runActivityStartedAtRef = useRef<Record<string, number>>({})
  const sessionMessagesCacheRef = useRef<Record<string, SessionDetail['messages']>>({})

  const setSendingForSession = useCallback((key: string, value: boolean) => {
    setSessionThinking(key, value)
    setSendingBySession(prev => {
      const next = { ...prev }
      if (value) {
        next[key] = true
      } else {
        delete next[key]
      }
      sendingBySessionRef.current = next
      return next
    })
  }, [setSessionThinking])

  const clearStreamingText = useCallback((key: string) => {
    targetTextBySessionRef.current[key] = ''
    setDisplayedTextBySession(prev => {
      if (!prev[key]) return prev
      const next = { ...prev }
      delete next[key]
      return next
    })
    if (typewriterTimersRef.current[key]) {
      clearInterval(typewriterTimersRef.current[key])
      delete typewriterTimersRef.current[key]
    }
  }, [])

  const setRunIdForSession = useCallback((key: string, runId: string | null) => {
    const next = { ...runIdBySessionRef.current }
    if (runId) {
      next[key] = runId
    } else {
      delete next[key]
    }
    runIdBySessionRef.current = next
  }, [])

  const clearActivityForSession = useCallback((key: string) => {
    setActivityBySession(prev => {
      if (!prev[key]) return prev
      const next = { ...prev }
      delete next[key]
      activityBySessionRef.current = next
      return next
    })
  }, [])

  const archiveActivityForSession = useCallback((key: string, runId?: string | null, visibleMessages?: SessionDetail['messages'], rawMessages?: SessionDetail['messages']) => {
    const liveEvents = activityBySessionRef.current[key] || []
    const latestTurn = rawMessages ? latestVisibleAssistantTurn(rawMessages) : []
    const rawProcessingEvents = latestTurn.length > 0 ? buildProcessingEvents(latestTurn) : []
    const events = liveEvents.length > 0 ? liveEvents : rawProcessingEvents
    const thoughts = latestTurn.length > 0 ? extractProcessingThoughts(latestTurn) : []
    if (events.length === 0 && thoughts.length === 0) return
    const resolvedRunId = runId || events[0]?.runId || runIdBySessionRef.current[key] || ''
    const endedAt = Date.now()
    const startedAt = runActivityStartedAtRef.current[key] || events[0]?.timestamp || endedAt
    const assistantIndex = rawMessages
      ? latestVisibleAssistantIndex(rawMessages)
      : visibleMessages
        ? visibleMessages.map(msg => msg.role).lastIndexOf('assistant')
      : undefined
    const archive: AgentActivityArchive = {
      id: String(resolvedRunId || key) + ':' + String(startedAt),
      runId: resolvedRunId,
      startedAt,
      endedAt,
      events,
      expanded: false,
      thoughts,
      toolEventsExpanded: false,
      durationReliable: liveEvents.length > 0,
      assistantIndex: assistantIndex !== undefined && assistantIndex >= 0 ? assistantIndex : undefined,
    }
    setActivityArchivesBySession(prev => {
      const current = prev[key] || []
      const deduped = current.filter(item => item.id !== archive.id)
      const archives = [...deduped, archive].slice(-6)
      saveActivityArchives(key, archives)
      return { ...prev, [key]: archives }
    })
  }, [])

  const closeRunEventStream = useCallback((key: string) => {
    const stream = runEventSourcesRef.current[key]
    if (stream) {
      stream.close()
      delete runEventSourcesRef.current[key]
    }
  }, [])

  const addActivityEvent = useCallback((key: string, event: AgentActivityEvent) => {
    setActivityBySession(prev => {
      const current = prev[key] || []
      const nextEvents = [...current.filter(item => item.id !== event.id), event]
        .sort((a, b) => a.timestamp - b.timestamp)
        .slice(-8)
      const next = { ...prev, [key]: nextEvents }
      activityBySessionRef.current = next
      return next
    })
  }, [])

  const setStreamingText = useCallback((key: string, text: string) => {
    if (!text) {
      clearStreamingText(key)
      return
    }

    targetTextBySessionRef.current[key] = text
    if (!typewriterTimersRef.current[key]) {
      typewriterTimersRef.current[key] = setInterval(() => {
        setDisplayedTextBySession(prev => {
          const target = targetTextBySessionRef.current[key] || ''
          const current = prev[key] || ''
          if (current.length >= target.length) {
            if (typewriterTimersRef.current[key]) {
              clearInterval(typewriterTimersRef.current[key])
              delete typewriterTimersRef.current[key]
            }
            return { ...prev, [key]: target }
          }
          const charsToAdd = Math.min(3, target.length - current.length)
          return { ...prev, [key]: target.substring(0, current.length + charsToAdd) }
        })
      }, 20)
    }
  }, [clearStreamingText])

  const applyLoadedMessages = useCallback((key: string, nextMessages: SessionDetail['messages']) => {
    const visibleMessages = filterVisibleMessages(nextMessages)
    setActivityArchivesBySession(prev => {
      if (prev[key]?.length) return prev
      const stored = loadActivityArchives(key)
      return stored.length ? { ...prev, [key]: stored } : prev
    })
    if (visibleMessages.length > 0) {
      sessionMessagesCacheRef.current[key] = visibleMessages
    }
    if (hasAssistantAfterLastUser(visibleMessages)) {
      clearStreamingText(key)
      if (activityBySessionRef.current[key]?.length || hasProcessingForLatestTurn(nextMessages)) {
        archiveActivityForSession(key, null, visibleMessages, nextMessages)
      }
      clearActivityForSession(key)
      closeRunEventStream(key)
      setRunIdForSession(key, null)
      sseCompletedRef.current[key] = true
      if (sendingBySessionRef.current[key]) {
        setSendingForSession(key, false)
      }
    }
    if (activeSessionKeyRef.current !== key) return
    setMessages(prev => {
      if (visibleMessages.length === 0 && prev.length > 0) {
        return prev
      }
      return visibleMessages
    })
  }, [archiveActivityForSession, clearActivityForSession, clearStreamingText, closeRunEventStream, setRunIdForSession, setSendingForSession])

  const [draftAgentId, setDraftAgentId] = useState('')
  const [isDraftSession, setIsDraftSession] = useState(false)
  const [agentPickerOpen, setAgentPickerOpen] = useState(false)
  const [agentCreateOpen, setAgentCreateOpen] = useState(false)
  const [agentSearch, setAgentSearch] = useState('')
  const [agentPickerStyle, setAgentPickerStyle] = useState<CSSProperties>({})
  const [agentPickerListMaxHeight, setAgentPickerListMaxHeight] = useState(288)
  const [modelChoices, setModelChoices] = useState<ModelChoice[]>([])
  const [selectedModel, setSelectedModel] = useState('')

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const slashMenuRef = useRef<HTMLDivElement>(null)
  const activeSessionKeyRef = useRef<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const agentPickerRef = useRef<HTMLDivElement>(null)
  const agentPickerButtonRef = useRef<HTMLButtonElement>(null)
  const sessionLoadSeqRef = useRef(0)
  const toast = useToast()

  useEffect(() => {
    listModels()
      .then(result => {
        setModelChoices(result.models || [])
        const stored = window.localStorage.getItem('openclaw:selected-model') || ''
        const configured = result.configuredModel || result.models?.[0]?.id || ''
        const next = result.models?.some(model => model.id === stored) ? stored : configured
        setSelectedModel(next)
      })
      .catch(() => {
        setModelChoices([])
      })
  }, [])

  useEffect(() => {
    if (selectedModel) {
      window.localStorage.setItem('openclaw:selected-model', selectedModel)
    }
  }, [selectedModel])

  const resolveKnownSessionKey = useCallback((rawKey: string): string => {
    const normalized = normalizeSessionKey(rawKey)
    const candidates = [
      activeSessionKeyRef.current,
      ...Object.keys(sendingBySessionRef.current),
      ...Object.keys(targetTextBySessionRef.current),
    ].filter(Boolean) as string[]
    return candidates.find(key => normalizeSessionKey(key) === normalized) || rawKey
  }, [])

  // Files
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([])

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, activeSessionKey, displayedTextBySession, activityBySession, scrollToBottom])

  useEffect(() => {
    const createdAgent = searchParams.get('createdAgent')
    if (!createdAgent) return
    toast.success('已创建 ' + createdAgent + '，可以开始对话了', 6000)
  }, [searchParams, toast])

  const updateAgentPickerPosition = useCallback(() => {
    const button = agentPickerButtonRef.current
    if (!button) return

    const rect = button.getBoundingClientRect()
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight
    const margin = 12
    const gap = 8
    const panelWidth = Math.min(320, viewportWidth - margin * 2)
    const left = Math.min(
      Math.max(rect.left, margin),
      viewportWidth - panelWidth - margin,
    )

    const spaceAbove = rect.top - margin
    const spaceBelow = viewportHeight - rect.bottom - margin
    const openBelow = spaceBelow >= 280 || spaceBelow > spaceAbove
    const availableSpace = Math.max(
      180,
      (openBelow ? spaceBelow : spaceAbove) - gap,
    )
    const panelMaxHeight = Math.min(420, availableSpace)
    const top = openBelow
      ? Math.min(rect.bottom + gap, viewportHeight - panelMaxHeight - margin)
      : Math.max(margin, rect.top - panelMaxHeight - gap)
    const reservedHeight = draftAgentId && !agentSearch.trim() ? 126 : 72

    setAgentPickerStyle({
      position: 'fixed',
      top,
      left,
      width: panelWidth,
      maxHeight: panelMaxHeight,
    })
    setAgentPickerListMaxHeight(Math.max(108, panelMaxHeight - reservedHeight))
  }, [agentSearch, draftAgentId])

  useEffect(() => {
    if (!agentPickerOpen) return
    const closeOnOutsideClick = (event: MouseEvent) => {
      const target = event.target as Node | null
      if (target && agentPickerRef.current?.contains(target)) return
      setAgentPickerOpen(false)
    }
    const updatePosition = () => updateAgentPickerPosition()
    requestAnimationFrame(updatePosition)
    document.addEventListener('mousedown', closeOnOutsideClick)
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      document.removeEventListener('mousedown', closeOnOutsideClick)
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [agentPickerOpen, updateAgentPickerPosition])

  // Restore session from URL param
  useEffect(() => {
    const sessionKey = searchParams.get('session')
    if (sessionKey && sessionKey !== activeSessionKey) {
      loadSession(sessionKey)
      return
    }
    if (!sessionKey && searchParams.get('new') !== '1') {
      sessionLoadSeqRef.current += 1
      setActiveSessionKey(null)
      activeSessionKeyRef.current = null
      setMessages([])
      setPendingFiles([])
      setChatLoading(false)
      setIsDraftSession(false)
    }
  }, [searchParams])

  useEffect(() => {
    if (searchParams.get('new') !== '1') return
    const agentId = searchParams.get('agent') || ''
    sessionLoadSeqRef.current += 1
    setActiveSessionKey(null)
    activeSessionKeyRef.current = null
    setMessages([])
    setPendingFiles([])
    setChatLoading(false)
    setIsDraftSession(true)
    setDraftAgentId(agentId)
    setAgentPickerOpen(false)
    setTimeout(() => inputRef.current?.focus(), 100)
  }, [searchParams])

  useEffect(() => {
    let cancelled = false
    const agentId = activeSessionKey
      ? getAgentIdFromKey(activeSessionKey)
      : draftAgentId || searchParams.get('agent') || 'main'

    setSlashCommandsLoading(true)
    setSlashCommandsError('')

    listSlashCommands(agentId)
      .then(result => {
        if (!cancelled) {
          setSlashCommands(buildSlashCommandItems(result.commands || []))
          setSlashCommandsError('')
        }
      })
      .catch((err: any) => {
        if (!cancelled) {
          setSlashCommands([])
          setSlashCommandsError(err?.message || '加载命令失败')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setSlashCommandsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [activeSessionKey, draftAgentId, searchParams])

  const loadSession = async (key: string, options: { force?: boolean } = {}) => {
    const loadSeq = sessionLoadSeqRef.current + 1
    sessionLoadSeqRef.current = loadSeq
    setActiveSessionKey(key)
    activeSessionKeyRef.current = key
    setIsDraftSession(false)
    setDraftAgentId(getAgentIdFromKey(key))
    setAgentPickerOpen(false)
    setChatLoading(true)
    setSearchParams({ session: key })
    const cachedMessages = sessionMessagesCacheRef.current[key]
    if (!options.force && cachedMessages) {
      setMessages(cachedMessages)
      setChatLoading(false)
      return
    }
    try {
      const detail = await getSession(key)
      if (sessionLoadSeqRef.current !== loadSeq || activeSessionKeyRef.current !== key) return
      applyLoadedMessages(key, detail.messages || [])
    } catch (err: any) {
      if (sessionLoadSeqRef.current !== loadSeq || activeSessionKeyRef.current !== key) return
      toast.error(err?.message || '加载对话失败')
      setMessages([])
    } finally {
      if (sessionLoadSeqRef.current === loadSeq && activeSessionKeyRef.current === key) {
        setChatLoading(false)
      }
    }
  }

  const createDraftSession = (agentId = '') => {
    sessionLoadSeqRef.current += 1
    setActiveSessionKey(null)
    activeSessionKeyRef.current = null
    setMessages([])
    setPendingFiles([])
    setIsDraftSession(true)
    setDraftAgentId(agentId)
    setSearchParams(agentId ? { new: '1', agent: agentId } : { new: '1' })
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
        id: String(Date.now()) + '-' + Math.random().toString(36).slice(2),
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

  // SSE connection for real-time chat events (replaces WebSocket)
  const sseRef = useRef<EventSource | null>(null)

  const handleChatEvent = useCallback((payload: any) => {
    const { state, sessionKey: rawSessionKey } = payload
    if (!rawSessionKey) {
      console.log('[SSE] skip: sessionKey is empty')
      return
    }

    const eventSessionKey = resolveKnownSessionKey(String(rawSessionKey))
    const isVisibleSession = eventSessionKey === activeSessionKeyRef.current
    console.log('[SSE] handleChatEvent:', { state, eventSessionKey, isVisibleSession })

    // Streaming delta: extract text and update incrementally
    if (state === 'delta' && payload.message) {
      const content = payload.message.content
      console.log('[SSE] delta鍐呭:', JSON.stringify(content)?.substring(0, 200))
      if (Array.isArray(content)) {
        const textPart = content.find((c: any) => c.type === 'text')
        if (textPart?.text) {
          setStreamingText(eventSessionKey, textPart.text)
        }
      } else if (typeof content === 'string') {
        setStreamingText(eventSessionKey, content)
      }
      return
    }

    // Started: clear streaming text for new turn
    if (state === 'started') {
      setStreamingText(eventSessionKey, '')
      return
    }

    // Final / error / aborted: load final messages, then clear streaming
    if (state === 'final' || state === 'error' || state === 'aborted') {
      // Keep streaming text visible until messages load.

      if (sseFinalTimersRef.current[eventSessionKey]) {
        clearTimeout(sseFinalTimersRef.current[eventSessionKey])
      }
      sseFinalTimersRef.current[eventSessionKey] = setTimeout(async () => {
        // No new final events for 3s means the agent is done.
        for (let attempt = 0; attempt < 8; attempt += 1) {
          try {
            const detail = await getSession(eventSessionKey)
            const loadedMessages = detail.messages || []
            applyLoadedMessages(eventSessionKey, loadedMessages)
            if (hasAssistantAfterLastUser(loadedMessages) || state === 'error' || state === 'aborted') {
              clearStreamingText(eventSessionKey)
              setSendingForSession(eventSessionKey, false)
              sseCompletedRef.current[eventSessionKey] = true
              refreshSessions({ silent: true, force: true })
              return
            }
          } catch {
            // keep retrying briefly; history may lag behind the lifecycle event
          }
          await new Promise(resolve => setTimeout(resolve, 1000))
        }

        clearStreamingText(eventSessionKey)
        setSendingForSession(eventSessionKey, false)
        sseCompletedRef.current[eventSessionKey] = true
        toast.error('回复还没有写入完成，请稍后刷新')
      }, 3000)
    }
  }, [applyLoadedMessages, clearStreamingText, refreshSessions, resolveKnownSessionKey, setSendingForSession, setStreamingText, toast])

  // Connect SSE on mount
  useEffect(() => {
    console.log('[SSE] useEffect triggered')
    const token = getAccessToken()
    if (!token) {
      console.log('[SSE] no token, skip SSE connection')
      return
    }
    // Always use relative URL so SSE goes through Vite proxy, avoiding CORS issues
    const url = '/api/openclaw/events/stream?token=' + encodeURIComponent(token)
    console.log('[SSE] connecting:', url)
    const sse = new EventSource(url)
    sseRef.current = sse

    sse.onopen = () => {
      console.log('[SSE] connected')
    }

    sse.onmessage = (evt) => {
      console.log('[SSE] message:', evt.data?.substring(0, 100))
      try {
        const msg = JSON.parse(evt.data)
        if (msg.event === 'chat' && msg.payload) {
          handleChatEvent(msg.payload)
        }
      } catch {
        // ignore
      }
    }

    sse.onerror = (e) => {
      console.log('[SSE] error, readyState:', sse.readyState, e)
    }

    return () => {
      console.log('[SSE] cleanup connection')
      Object.values(sseFinalTimersRef.current).forEach(timer => clearTimeout(timer))
      sseFinalTimersRef.current = {}
      Object.values(typewriterTimersRef.current).forEach(timer => clearInterval(timer))
      typewriterTimersRef.current = {}
      Object.values(runEventSourcesRef.current).forEach(stream => stream.close())
      runEventSourcesRef.current = {}
      runStreamDoneRef.current = {}
      sse.close()
      sseRef.current = null
    }
  }, [handleChatEvent])

  const streamRunActivity = useCallback((key: string, runId: string): RunActivityStream => {
    closeRunEventStream(key)
    delete runStreamDoneRef.current[key]
    runActivityStartedAtRef.current[key] = Date.now()

    const sse = new EventSource(getRunEventsStreamUrl(runId))
    runEventSourcesRef.current[key] = sse
    let sawEvent = false
    let settled = false
    let resolveDone: (result: RunStreamResult) => void = () => {}
    const done = new Promise<RunStreamResult>(resolve => {
      resolveDone = resolve
    })
    const ready = new Promise<boolean>(resolve => {
      const readyTimer = window.setTimeout(() => resolve(sawEvent), 3500)
      sse.onopen = () => {
        window.clearTimeout(readyTimer)
        resolve(true)
      }
    })

    const finishStream = (result: RunStreamResult) => {
      if (settled) return
      settled = true
      runStreamDoneRef.current[key] = result
      sseCompletedRef.current[key] = true
      closeRunEventStream(key)
      resolveDone(result)
    }

    sse.onmessage = (evt) => {
      if (abortedSessionRef.current[key]) return
      try {
        const payload = JSON.parse(evt.data)
        const eventType = String(payload.type || payload.event || '')
        const eventRunId = typeof payload.run_id === 'string' ? payload.run_id : runId
        if (eventRunId && eventRunId !== runId) return
        sawEvent = true

        if (eventType === 'message.delta') {
          const delta = typeof payload.delta === 'string' ? payload.delta : ''
          if (delta) {
            const current = targetTextBySessionRef.current[key] || ''
            setStreamingText(key, current + delta)
          }
          return
        }

        if (eventType === 'approval.responded') {
          const choice = typeof payload.choice === 'string' ? payload.choice : ''
          setActivityBySession(prev => {
            const current = prev[key] || []
            const next = {
              ...prev,
              [key]: current.map(activity => activity.type === 'approval.request'
                ? {
                    ...activity,
                    title: choice ? '已授权：' + approvalChoiceLabel(choice) : '授权已处理',
                    status: 'completed' as AgentActivityStatus,
                    selectedChoice: choice,
                    responding: false,
                  }
                : activity),
            }
            activityBySessionRef.current = next
            return next
          })
          return
        }

        if (eventType === 'tool.started' || eventType === 'tool.completed' || eventType === 'reasoning.available' || eventType === 'approval.request' || eventType === 'run.failed') {
          const status: AgentActivityStatus =
            eventType === 'tool.completed'
              ? payload.error ? 'failed' : 'completed'
              : eventType === 'reasoning.available'
                ? 'thinking'
                : eventType === 'approval.request'
                  ? 'approval'
                  : eventType === 'run.failed'
                    ? 'failed'
                    : 'running'
          const eventKey = payload.tool || payload.tool_call_id || payload.preview || eventType
          addActivityEvent(key, {
            id: String(eventType) + ':' + String(eventKey),
            runId,
            type: eventType,
            title: buildActivityTitle(eventType, payload),
            detail: buildActivityDetail(eventType, payload),
            status,
            timestamp: typeof payload.timestamp === 'number' ? payload.timestamp * 1000 : Date.now(),
            choices: eventType === 'approval.request' ? normalizeApprovalChoices(payload) : undefined,
          })
          if (eventType === 'run.failed') {
            finishStream('failed')
          }
          return
        }

        if (eventType === 'run.completed' || eventType === 'run.cancelled') {
          finishStream(eventType === 'run.completed' ? 'completed' : 'cancelled')
        }
      } catch {
        // ignore malformed event chunks
      }
    }

    sse.onerror = () => {
      finishStream(sawEvent ? 'error' : 'error')
    }

    return { ready, done }
  }, [addActivityEvent, closeRunEventStream, setStreamingText])

  const loadFinalMessages = useCallback(async (key: string, failed = false) => {
    const maxLoadAttempts = failed ? 3 : 8
    for (let attempt = 0; attempt < maxLoadAttempts; attempt += 1) {
      const detail = await getSession(key)
      const loadedMessages = detail.messages || []
      applyLoadedMessages(key, loadedMessages)
      if (hasAssistantAfterLastUser(loadedMessages) || failed || attempt === maxLoadAttempts - 1) {
        clearStreamingText(key)
        sseCompletedRef.current[key] = true
        return
      }
      await new Promise(r => setTimeout(r, 1000))
    }
  }, [applyLoadedMessages, clearStreamingText])

  const waitForResponse = async (key: string, runId: string | null, stream?: RunActivityStream | null) => {
    // SSE handles incremental display. Completion should come from runId-based
    // waiting so we don't mistake a partial assistant message for a finished turn.
    sseCompletedRef.current[key] = false
    if (runId && stream) {
      const streamReady = await stream.ready
      if (streamReady) {
        const result = await stream.done
        if (abortedSessionRef.current[key]) return
        await loadFinalMessages(key, result === 'failed' || result === 'error')
        if (result === 'failed' || result === 'error') {
          toast.error('Agent 执行出错，请稍后重试')
        }
        return
      }
    }
    const maxWaitMs = 900000 // Allow longer tool-heavy agent runs.
    const perRequestTimeoutMs = 25000
    const startTime = Date.now()

    while (Date.now() - startTime < maxWaitMs) {
      if (abortedSessionRef.current[key]) return
      if (sseCompletedRef.current[key]) return
      if (runId) {
        try {
          const remainingMs = maxWaitMs - (Date.now() - startTime)
          const waitResult = await waitForAgentRun(runId, Math.min(perRequestTimeoutMs, remainingMs))

          if (sseCompletedRef.current[key]) return

          if (waitResult.status === 'timeout') {
            continue
          }

          const finished = isRunFinished(waitResult.status)
          if (finished) {
            await loadFinalMessages(key, isRunFailed(waitResult.status))
            if (isRunFailed(waitResult.status)) {
              toast.error('Agent 执行出错，请稍后重试')
            }
            return
          }
          const maxLoadAttempts = 1
          for (let attempt = 0; attempt < maxLoadAttempts; attempt += 1) {
            const detail = await getSession(key)
            const loadedMessages = detail.messages || []
            applyLoadedMessages(key, loadedMessages)
            if (hasAssistantAfterLastUser(loadedMessages) || attempt === maxLoadAttempts - 1) {
              if (hasAssistantAfterLastUser(loadedMessages) || finished) {
                clearStreamingText(key)
                sseCompletedRef.current[key] = true
                if (isRunFailed(waitResult.status)) {
                  toast.error('Agent 执行出错，请稍后重试')
                }
                return
              }
            }
            await new Promise(r => setTimeout(r, 1000))
          }
          await new Promise(r => setTimeout(r, 1200))
          continue
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
        if (lastMsg?.role === 'assistant' && hasAssistantAfterLastUser(msgs) && !targetTextBySessionRef.current[key]) {
          applyLoadedMessages(key, msgs)
          clearStreamingText(key)
          sseCompletedRef.current[key] = true
          return
        }
      } catch {
        // ignore and keep waiting
      }
    }

    // Timeout: load final state
    try {
      await loadFinalMessages(key)
    } catch {}
    clearStreamingText(key)
    sseCompletedRef.current[key] = true
  }

  const handleSend = async () => {
    const text = input.trim()
    if ((!text && pendingFiles.length === 0) || (!activeSessionKeyRef.current && !isDraftSession) || chatLoading) return
    if (!selectedModel) {
      toast.error('暂无可用模型，请联系管理员配置模型 Key')
      return
    }

    const requestedAgentId = draftAgentId || searchParams.get('agent') || 'main'
    const sendingSessionKey = activeSessionKeyRef.current || 'agent:' + (requestedAgentId || 'main') + ':session-' + Date.now()
    if (sendingBySession[sendingSessionKey]) return
    abortedSessionRef.current[sendingSessionKey] = false
    const isFirstTurn = !activeSessionKeyRef.current
    let firstTurnTitle = ''
    if (isFirstTurn) {
      const now = new Date().toISOString()
      firstTurnTitle = pendingFiles.length > 0 && !text ? buildFallbackTitleFromText(pendingFiles.length) : '新对话'
      const optimisticSession: Session = {
        key: sendingSessionKey,
        title: firstTurnTitle,
        created_at: now,
        updated_at: now,
      }
      addOptimisticSession(optimisticSession)
      setActiveSessionKey(sendingSessionKey)
      activeSessionKeyRef.current = sendingSessionKey
      setIsDraftSession(false)
      setAgentPickerOpen(false)
      setSearchParams({ session: sendingSessionKey })
    }
    setSendingForSession(sendingSessionKey, true)
    clearActivityForSession(sendingSessionKey)

    try {
      const agentId = getAgentIdFromKey(sendingSessionKey)
      const uploadDir = getUploadDir(agentId)

      // Upload all files to agent workspace
      const uploadedPaths: string[] = []
      for (const pf of pendingFiles) {
        const result = await uploadFileToWorkspace(pf.file, uploadDir)
        const uploadedPath = result.path || result.name || pf.name
        uploadedPaths.push(uploadedPath)
      }

      // Build final message with file references
      let finalMessage = text
      if (uploadedPaths.length > 0) {
        const fileRefs = uploadedPaths
          .map(p => '[Attachment: ~/.openclaw/' + p + ']')
          .join('\n')
        finalMessage = finalMessage
          ? finalMessage + '\n\n' + fileRefs
          : fileRefs
      }

      // Optimistic UI
      const displayParts: string[] = []
      if (text) displayParts.push(text)
      if (uploadedPaths.length > 0) {
        uploadedPaths.forEach(p => {
          const name = p.split('/').pop() || p
          displayParts.push('File: ' + name)
        })
      }

      const userMsg = {
        role: 'user',
        content: displayParts.join('\n'),
        timestamp: new Date().toISOString(),
      }
      setMessages(prev => {
        const next = [...prev, userMsg]
        sessionMessagesCacheRef.current[sendingSessionKey] = next
        return next
      })
      setInput('')
      pendingFiles.forEach(pf => {
        if (pf.previewUrl) URL.revokeObjectURL(pf.previewUrl)
      })
      setPendingFiles([])

      clearStreamingText(sendingSessionKey)
      const titlePromise = isFirstTurn && text
        ? generateSessionTitle(sendingSessionKey, text)
          .then(result => {
            if (!result.title) return
            const now = new Date().toISOString()
            addOptimisticSession({
              key: sendingSessionKey,
              title: result.title,
              created_at: now,
              updated_at: now,
            })
            void refreshSessions({ silent: true, force: true })
          })
          .catch(() => {})
        : Promise.resolve()
      const sendResult = await sendChatMessage(sendingSessionKey, finalMessage, selectedModel)
      if (sendResult.title) {
        const now = new Date().toISOString()
        addOptimisticSession({
          key: sendingSessionKey,
          title: sendResult.title,
          created_at: now,
          updated_at: now,
        })
      }
      setRunIdForSession(sendingSessionKey, sendResult.runId)
      let activityStream: RunActivityStream | null = null
      if (sendResult.runId) {
        activityStream = streamRunActivity(sendingSessionKey, sendResult.runId)
      }
      if (abortedSessionRef.current[sendingSessionKey]) {
        if (sendResult.runId) {
          await abortAgentRun(sendResult.runId, sendingSessionKey)
        } else {
          await abortActiveSessionRun(sendingSessionKey)
        }
        return
      }
      void titlePromise
      await waitForResponse(sendingSessionKey, sendResult.runId, activityStream)
      void refreshSessions({ silent: true, force: true })
    } catch (err: any) {
      if (!abortedSessionRef.current[sendingSessionKey]) {
        toast.error(err?.message || '发送失败')
      }
    } finally {
      setSendingForSession(sendingSessionKey, false)
      setRunIdForSession(sendingSessionKey, null)
      closeRunEventStream(sendingSessionKey)
    }
  }

  const handleAbortCurrentRun = async () => {
    const key = activeSessionKeyRef.current
    if (!key || !sendingBySessionRef.current[key]) return

    abortedSessionRef.current[key] = true
    sseCompletedRef.current[key] = true
    if (sseFinalTimersRef.current[key]) {
      clearTimeout(sseFinalTimersRef.current[key])
      delete sseFinalTimersRef.current[key]
    }
    clearStreamingText(key)
    clearActivityForSession(key)
    closeRunEventStream(key)
    setSendingForSession(key, false)
    setRunIdForSession(key, null)

    try {
      const runId = runIdBySessionRef.current[key]
      if (runId) {
        await abortAgentRun(runId, key)
      } else {
        await abortActiveSessionRun(key)
      }
      const detail = await getSession(key).catch(() => null)
      if (detail) {
        applyLoadedMessages(key, detail.messages || [])
      }
      void refreshSessions({ silent: true, force: true })
    } catch (err: any) {
      toast.error(err?.message || '终止失败')
    }
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
      setSlashMenuDismissed(true)
      return
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleRefresh = () => {
    if (activeSessionKey) {
      loadSession(activeSessionKey, { force: true })
    }
  }

  const handleSelectDraftAgent = (agentId: string) => {
    setDraftAgentId(agentId)
    setAgentPickerOpen(false)
    setAgentSearch('')
    setSearchParams({ new: '1', agent: agentId })
  }

  const handleClearDraftAgent = () => {
    setDraftAgentId('')
    setAgentPickerOpen(false)
    setAgentSearch('')
    setSearchParams({ new: '1' })
  }

  const handleAgentCreated = async (agentId: string, displayName: string) => {
    setAgentCreateOpen(false)
    toast.success('已创建 ' + displayName + '，可以开始对话了', 6000)
    await refreshAgents({ force: true })
    handleSelectDraftAgent(agentId)
  }

  const applySlashCommand = (command: SlashCommandItem) => {
    setInput('/' + command.name + ' ')
    setSlashActiveIndex(0)
    setSlashMenuDismissed(false)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  const formatTime = (iso: string | null) => {
    if (!iso) return ''
    const d = new Date(iso)
    const now = new Date()
    const isToday = d.toDateString() === now.toDateString()
    const time = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
    if (isToday) return time
    return String(d.getMonth() + 1) + '/' + String(d.getDate()) + ' ' + time
  }

  const hasContent = input.trim() || pendingFiles.length > 0
  const isCurrentSending = Boolean(activeSessionKey && sendingBySession[activeSessionKey])
  const slashQuery = getSlashQuery(input)
  const filteredSlashCommands = filterSlashCommands(slashCommands, slashQuery || '')
  const showSlashMenu = slashQuery !== null && !slashMenuDismissed && !chatLoading && !isCurrentSending
  const groupedSlashCommands = filteredSlashCommands.reduce<Record<string, SlashCommandItem[]>>((acc, command) => {
    const key = command.category
    if (!acc[key]) acc[key] = []
    acc[key].push(command)
    return acc
  }, {})

  useEffect(() => {
    setSlashActiveIndex(0)
    setSlashMenuDismissed(false)
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

  const displayedText = activeSessionKey ? displayedTextBySession[activeSessionKey] || '' : ''
  const currentActivity = activeSessionKey ? activityBySession[activeSessionKey] || [] : []
  const currentActivityArchives = activeSessionKey ? activityArchivesBySession[activeSessionKey] || [] : []
  const archiveByAssistantIndex = useMemo(() => {
    const map = new Map<number, AgentActivityArchive>()
    currentActivityArchives.forEach(archive => {
      if (typeof archive.assistantIndex === 'number') {
        map.set(archive.assistantIndex, archive)
      }
    })
    return map
  }, [currentActivityArchives])
  const isDraftStart = isDraftSession && messages.length === 0 && !activeSessionKey
  const agentOptions = useMemo(() => {
    const hasMain = agents.some(agent => agent.id === 'main')
    const mainAgent: AgentInfo = {
      id: 'main',
      name: '\u4e3b\u52a9\u624b',
      identity: { name: '\u4e3b\u52a9\u624b' },
    }
    const visibleAgents = hasMain ? agents : [mainAgent, ...agents]
    return [...visibleAgents].sort((a, b) => {
      if (a.id === 'main') return -1
      if (b.id === 'main') return 1
      const aName = a.identity?.name || a.name || a.id
      const bName = b.identity?.name || b.name || b.id
      return aName.localeCompare(bName, 'zh-Hans')
    })
  }, [agents])
  const currentAgentId = activeSessionKey ? getAgentIdFromKey(activeSessionKey) : draftAgentId
  const selectedAgent = currentAgentId ? agentOptions.find(agent => agent.id === currentAgentId) : null
  const selectedAgentLabel =
    !currentAgentId || currentAgentId === 'main'
      ? '\u4e3b\u52a9\u624b'
      : selectedAgent?.identity?.name || selectedAgent?.name || currentAgentId || '未知 Agent'
  const conversationTitle = isDraftStart
    ? '新对话'
    : currentSessionTitle?.trim() ||
      buildTitleFromMessages(messages) ||
      selectedAgentLabel + ' 对话'
  const agentQuery = agentSearch.trim().toLowerCase()
  const selectableAgents = agentOptions.filter(agent => agent.id !== 'main')
  const filteredAgents = selectableAgents.filter(agent => {
    if (!agentQuery) return true
    const values = [agent.id, agent.name, agent.identity?.name].filter(Boolean).join(' ').toLowerCase()
    return values.includes(agentQuery)
  })
  const canChangeAgent = isDraftSession && messages.length === 0 && !isCurrentSending

  const pendingFilesPreview = pendingFiles.length > 0 && (
    <div className="flex flex-wrap gap-2">
      {pendingFiles.map(pf => (
        <div
          key={pf.id}
          className="relative group rounded-lg border border-light-border bg-light-card overflow-hidden"
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
                <div className="text-xs text-light-text truncate max-w-[120px]">{pf.name}</div>
                <div className="text-[10px] text-light-text-secondary">{formatFileSize(pf.file.size)}</div>
              </div>
            </div>
          )}
          <span className="absolute top-0.5 right-0.5 opacity-0 transition-opacity group-hover:opacity-100">
            <Tooltip content={'移除附件 ' + pf.name}>
              <button
                onClick={() => removePendingFile(pf.id)}
                className="flex h-4 w-4 items-center justify-center rounded-full bg-black/60 text-white transition-colors hover:bg-black/75"
              >
                <X size={10} />
              </button>
            </Tooltip>
          </span>
        </div>
      ))}
    </div>
  )

  const agentPicker = agentPickerOpen && canChangeAgent && (
    <div
      className="z-40 flex flex-col overflow-hidden rounded-2xl border border-light-border bg-white p-3 shadow-xl shadow-slate-200/80"
      style={agentPickerStyle}
    >
      <div className="mb-2 flex items-center gap-2 rounded-xl border border-light-border px-3 py-2 text-sm text-light-text-secondary">
        <Search size={15} />
        <ClearableInput
          value={agentSearch}
          onValueChange={setAgentSearch}
          className="min-w-0 flex-1 bg-transparent text-sm text-light-text outline-none placeholder:text-light-text-secondary"
          placeholder="搜索 Agent"
          autoFocus
          clearLabel="清空 Agent 搜索"
        />
      </div>
      <div className="overflow-y-auto pr-1" style={{ maxHeight: agentPickerListMaxHeight }}>
        {filteredAgents.length === 0 ? (
          <div className="px-2 py-4 text-center text-xs text-light-text-secondary">没有匹配的 Agent</div>
        ) : filteredAgents.map(agent => {
          const label = agent.identity?.name || agent.name || agent.id
          const description = agentDescriptions[agent.id] || '专用任务助手'
          const selected = Boolean(draftAgentId) && agent.id === draftAgentId
          return (
            <button
              key={agent.id}
              onClick={() => handleSelectDraftAgent(agent.id)}
              className="flex w-full cursor-pointer items-center gap-3 rounded-xl px-3 py-2 text-left text-sm transition-colors hover:bg-light-card-hover"
            >
              <Bot size={16} className="text-accent-blue" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-light-text">{label}</div>
                <div className="truncate text-xs text-light-text-secondary">{description}</div>
              </div>
              {selected && <Check size={15} className="text-accent-blue" />}
            </button>
          )
        })}
      </div>
      <div className="mt-2 space-y-1 border-t border-light-border pt-2">
        {draftAgentId && !agentQuery && (
          <button
            onClick={handleClearDraftAgent}
            className="flex w-full cursor-pointer items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-light-text-secondary transition-colors hover:bg-light-card-hover hover:text-light-text"
          >
            <X size={16} />
            <span>Use main assistant</span>
          </button>
        )}
        <button
          onClick={() => {
            setAgentPickerOpen(false)
            setAgentCreateOpen(true)
          }}
          className="flex w-full cursor-pointer items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-light-text-secondary transition-colors hover:bg-light-card-hover hover:text-light-text"
        >
          <Plus size={16} />
          <span>Create a dedicated Agent</span>
        </button>
      </div>
    </div>
  )

  const renderAgentSelector = (compact = false) => (
    <div ref={agentPickerRef} className="relative">
      <button
        ref={agentPickerButtonRef}
        onClick={() => {
          if (!canChangeAgent) return
          setAgentPickerOpen(value => !value)
        }}
        disabled={!canChangeAgent}
        className={'flex items-center gap-2 rounded-xl border border-light-border bg-light-card px-3 py-1.5 text-xs transition-colors ' + (
          canChangeAgent
            ? 'cursor-pointer text-light-text-secondary hover:border-accent-blue/30 hover:text-light-text'
            : 'cursor-not-allowed text-light-text-secondary/60'
        ) + ' ' + (compact && !draftAgentId ? 'text-accent-blue' : '')}
        title={canChangeAgent ? 'Select Agent' : 'Current chat is locked to this Agent'}
      >
        <Bot size={14} />
        <span className="max-w-[180px] truncate">{selectedAgentLabel}</span>
        <ChevronDown size={13} />
      </button>
      {agentPicker}
    </div>
  )

  const renderModelSelector = () => (
    <label className="flex items-center gap-1.5 rounded-xl border border-light-border bg-light-card px-2 py-1 text-xs text-light-text-secondary">
      <Brain size={14} />
      <select
        value={selectedModel}
        onChange={event => setSelectedModel(event.target.value)}
        disabled={modelChoices.length === 0 || isCurrentSending}
        className="max-w-[220px] bg-transparent text-light-text outline-none disabled:text-light-text-secondary"
        title="选择模型"
      >
        {modelChoices.length === 0 ? (
          <option value="">暂无可用模型</option>
        ) : modelChoices.map(model => (
          <option key={model.id} value={model.id}>
            {(model.providerName || model.provider) + ' / ' + (model.name || model.id)}
          </option>
        ))}
      </select>
    </label>
  )

  const renderActivityIcon = (activity: AgentActivityEvent) => {
    const iconClass = activity.status === 'failed'
      ? 'text-accent-red'
      : activity.status === 'completed'
        ? 'text-accent-green'
        : activity.status === 'approval'
          ? 'text-accent-yellow'
          : 'text-accent-blue'

    if (activity.status === 'completed') return <CircleCheck size={14} className={iconClass} />
    if (activity.status === 'failed') return <AlertCircle size={14} className={iconClass} />
    if (activity.status === 'thinking') return <Brain size={14} className={iconClass} />
    if (activity.status === 'approval') return <ShieldQuestion size={14} className={iconClass} />
    return <Wrench size={14} className={iconClass + ' ' + (activity.status === 'running' ? 'animate-pulse' : '')} />
  }

  const handleApprovalChoice = useCallback(async (activity: AgentActivityEvent, choice: string) => {
    const key = activeSessionKeyRef.current
    if (!key) return
    setActivityBySession(prev => ({
      ...prev,
      [key]: (prev[key] || []).map(item => item.id === activity.id ? { ...item, responding: true } : item),
    }))
    activityBySessionRef.current = {
      ...activityBySessionRef.current,
      [key]: (activityBySessionRef.current[key] || []).map(item => item.id === activity.id ? { ...item, responding: true } : item),
    }
    try {
      await respondRunApproval(activity.runId, choice)
      setActivityBySession(prev => {
        const next = {
          ...prev,
          [key]: (prev[key] || []).map(item => item.id === activity.id
          ? {
              ...item,
                    title: '已授权：' + approvalChoiceLabel(choice),
              selectedChoice: choice,
              responding: false,
              status: 'completed' as AgentActivityStatus,
            }
          : item),
        }
        activityBySessionRef.current = next
        return next
      })
      toast.info('授权已提交')
    } catch (err: any) {
      setActivityBySession(prev => {
        const next = {
          ...prev,
          [key]: (prev[key] || []).map(item => item.id === activity.id ? { ...item, responding: false } : item),
        }
        activityBySessionRef.current = next
        return next
      })
      toast.error(err?.message || '授权提交失败')
    }
  }, [toast])

  const renderApprovalActions = (activity: AgentActivityEvent) => {
    if (activity.type !== 'approval.request' || activity.status !== 'approval') return null
    const choices = activity.choices && activity.choices.length > 0
      ? activity.choices
      : ['once', 'deny']
    return (
      <div className="mt-2 flex flex-wrap gap-1.5">
        {choices.map(choice => {
          const isDeny = choice === 'deny'
          return (
            <button
              key={choice}
              type="button"
              disabled={activity.responding}
              onClick={() => handleApprovalChoice(activity, choice)}
              className={'rounded-md border px-2 py-1 text-[11px] font-medium transition-colors disabled:cursor-wait disabled:opacity-60 ' + (
                isDeny
                  ? 'border-accent-red/25 bg-white text-accent-red hover:bg-accent-red/5'
                  : 'border-accent-blue/25 bg-white text-accent-blue hover:bg-accent-blue/5'
              )}
            >
              {activity.responding ? '提交中...' : approvalChoiceLabel(choice)}
            </button>
          )
        })}
      </div>
    )
  }

  const renderActivityRows = (events: AgentActivityEvent[]) => (
    <>
      {events.map(activity => (
        <div key={activity.id} className="flex min-w-0 items-start gap-2 text-xs">
          <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
            {renderActivityIcon(activity)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium text-light-text">{activity.title}</span>
            {activity.detail && (
              <span className="mt-0.5 block line-clamp-2 break-words text-light-text-secondary">
                {activity.detail}
              </span>
            )}
            {renderApprovalActions(activity)}
          </span>
        </div>
      ))}
    </>
  )

  const renderAgentActivity = (events = currentActivity, compact = false) => {
    if (events.length === 0) return null
    return (
      <div className={(compact ? 'mt-2' : 'mb-3') + ' space-y-1.5 rounded-lg border border-light-border bg-light-card-hover/55 px-3 py-2'}>
        <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-normal text-light-text-secondary">
          <Bot size={12} />
          Agent 正在执行
        </div>
        {renderActivityRows(events)}
      </div>
    )
  }

  const toggleActivityArchive = useCallback((archiveId: string) => {
    const key = activeSessionKeyRef.current
    if (!key) return
    setActivityArchivesBySession(prev => {
      const archives = (prev[key] || []).map(item => item.id === archiveId ? { ...item, expanded: !item.expanded } : item)
      saveActivityArchives(key, archives)
      return { ...prev, [key]: archives }
    })
  }, [])

  const toggleArchiveTools = useCallback((archiveId: string) => {
    const key = activeSessionKeyRef.current
    if (!key) return
    setActivityArchivesBySession(prev => {
      const archives = (prev[key] || []).map(item => item.id === archiveId ? { ...item, toolEventsExpanded: !item.toolEventsExpanded } : item)
      saveActivityArchives(key, archives)
      return { ...prev, [key]: archives }
    })
  }, [])

  const renderActivityArchive = (archive?: AgentActivityArchive) => {
    if (!archive || (archive.events.length === 0 && !(archive.thoughts?.length))) return null
    return (
      <div className="mb-3 border-b border-light-border pb-3">
        <button
          type="button"
          onClick={() => toggleActivityArchive(archive.id)}
          className="flex items-center gap-1.5 text-xs text-light-text-secondary transition-colors hover:text-light-text"
        >
          <span>
            {archive.durationReliable === false
              ? '已处理'
              : '已处理 ' + formatActivityDuration(archive.endedAt - archive.startedAt)}
          </span>
          <ChevronRight
            size={13}
            className={'transition-transform ' + (archive.expanded ? 'rotate-90' : '')}
          />
        </button>
        {archive.expanded && (
          <div className="mt-3 space-y-3">
            {archive.thoughts?.map((thought, index) => (
              <p key={archive.id + ':thought:' + index} className="text-sm leading-relaxed text-light-text">
                {thought}
              </p>
            ))}
            {archive.events.length > 0 && (
              <div>
                <button
                  type="button"
                  onClick={() => toggleArchiveTools(archive.id)}
                  className="flex items-center gap-1.5 text-xs text-light-text-secondary transition-colors hover:text-light-text"
                >
                  <Wrench size={12} />
                  <span>运行了 {archive.events.length} 个命令</span>
                  <ChevronRight
                    size={13}
                    className={'transition-transform ' + (archive.toolEventsExpanded ? 'rotate-90' : '')}
                  />
                </button>
                {archive.toolEventsExpanded && renderAgentActivity(archive.events, true)}
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  const renderComposer = (hero = false) => (
    <div className={hero ? 'relative rounded-[26px] border border-light-border bg-white p-3 shadow-lg shadow-slate-200/80' : 'relative mx-auto max-w-4xl rounded-[26px] border border-light-border bg-white p-3 shadow-lg shadow-slate-200/70'}>
      {showSlashMenu && (
        <div
          ref={slashMenuRef}
          className={
            'absolute inset-x-3 z-30 overflow-y-auto rounded-2xl border border-light-border bg-white shadow-xl ' +
            (hero
              ? 'top-[calc(100%+0.5rem)] max-h-[42vh]'
              : 'bottom-[calc(100%+0.5rem)] max-h-72')
          }
        >
          {filteredSlashCommands.length === 0 ? (
            <div className="px-4 py-3 text-sm text-light-text-secondary">
              {slashCommandsLoading
                ? '正在加载 Hermes 命令...'
                : slashCommandsError
                  ? '命令加载失败：' + slashCommandsError
                  : slashCommands.length === 0
                    ? '暂无可用 Hermes 命令'
                    : '没有匹配的命令'}
            </div>
          ) : (
            Object.entries(groupedSlashCommands).map(([category, commands]) => {
              const categoryKey = category as keyof typeof CATEGORY_LABELS
              const styles = CATEGORY_STYLES[categoryKey]
              return (
              <div key={category} className="border-b border-light-border last:border-b-0">
                <div className={'px-4 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-normal ' + styles.header}>
                  <span className={'rounded-full border px-2 py-0.5 ' + styles.badge}>
                    {CATEGORY_LABELS[categoryKey]}
                  </span>
                </div>
                <div className="pb-2">
                  {commands.map(command => {
                    const index = filteredSlashCommands.findIndex(item => item.name === command.name)
                    const isActive = index === slashActiveIndex
                    return (
                      <button
                        key={command.source + '-' + command.name}
                        type="button"
                        data-active={isActive ? 'true' : 'false'}
                        onMouseDown={event => event.preventDefault()}
                        onMouseEnter={() => setSlashActiveIndex(index)}
                        onClick={() => applySlashCommand(command)}
                        className={'flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors ' + (
                          isActive ? styles.active : 'hover:bg-light-card-hover'
                        )}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="flex min-w-0 items-center gap-2">
                            <span className={'truncate text-sm font-medium ' + (isActive ? styles.command : 'text-light-text')}>
                              /{command.name}
                            </span>
                            {command.argsHint && (
                              <span className="truncate text-xs text-light-text-secondary">
                                {command.argsHint}
                              </span>
                            )}
                          </span>
                          <span className="mt-0.5 block line-clamp-2 text-xs text-light-text-secondary">
                            {command.description}
                          </span>
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
              )
            })
          )}
        </div>
      )}
      {pendingFilesPreview && (
        <div className="px-2 pb-2">{pendingFilesPreview}</div>
      )}
      <div className="flex flex-col">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileSelect}
          className="hidden"
        />
        <ClearableTextarea
          ref={inputRef}
          value={input}
          onValueChange={(value) => {
            setInput(value)
            if (!value.startsWith('/')) setSlashMenuDismissed(false)
          }}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={hero ? '给 Hermes 发送消息，输入 / 查看命令' : '继续提问，输入 / 查看命令'}
          rows={hero ? 3 : 2}
          className="min-h-[72px] w-full resize-none bg-transparent px-2 py-2 text-[15px] text-light-text outline-none placeholder:text-slate-400"
          disabled={isCurrentSending}
          clearLabel="清空消息"
        />
        <div className="mt-2 flex items-center justify-between gap-3 px-1">
          <div className="flex min-w-0 items-center gap-2">
            <IconButton
              label="上传附件"
              onClick={() => fileInputRef.current?.click()}
              disabled={isCurrentSending}
              size="md"
              tone="primary"
              className="h-9 w-9 rounded-xl"
            >
              <Plus size={18} />
            </IconButton>
            {renderAgentSelector(true)}
            {renderModelSelector()}
          </div>
          {isCurrentSending ? (
            <IconButton
              label="缁堟鍥炲"
              onClick={handleAbortCurrentRun}
              surface="plain"
              className="h-9 w-9 rounded-full !bg-[var(--color-accent-blue)] !text-white transition-colors duration-150 hover:!bg-[color-mix(in_srgb,var(--color-accent-blue)_82%,white)] hover:!text-white"
            >
              <Square size={14} />
            </IconButton>
          ) : (
            <IconButton
              label="发送"
              onClick={handleSend}
              disabled={!hasContent}
              surface="plain"
              className="h-9 w-9 rounded-full !bg-[var(--color-accent-blue)] !text-white transition-colors duration-150 hover:!bg-[color-mix(in_srgb,var(--color-accent-blue)_82%,white)] hover:!text-white disabled:!bg-slate-300"
            >
              <Send size={16} />
            </IconButton>
          )}
        </div>
      </div>
    </div>
  )

  return (
    <div className="flex h-full">
      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {activeSessionKey || isDraftSession ? (
          <>
            {/* Chat header */}
            <div className="px-5 py-3 border-b border-light-border flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <IconButton
                  label="灞曞紑鑿滃崟"
                  onClick={openMobileSidebar}
                  size="md"
                  surface="plain"
                  className="-ml-2 lg:hidden"
                >
                  <Menu size={20} />
                </IconButton>
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent-blue/10 text-accent-blue">
                  <Bot size={16} />
                </div>
                <span className="truncate text-sm font-medium text-light-text" title={conversationTitle}>
                  {conversationTitle}
                </span>
                {!isDraftStart && selectedAgentLabel && (
                  <span className="hidden shrink-0 rounded-full border border-light-border px-2 py-0.5 text-xs text-light-text-secondary sm:inline">
                    {selectedAgentLabel}
                  </span>
                )}
              </div>
              {activeSessionKey && (
                <IconButton
                  label="鍒锋柊"
                  onClick={handleRefresh}
                  size="sm"
                >
                  <RefreshCw size={14} />
                </IconButton>
              )}
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {chatLoading ? (
                <ChatHistorySkeleton />
              ) : messages.length === 0 && !isDraftSession ? (
                <div className="flex flex-col items-center justify-center py-20 text-light-text-secondary">
                  <MessageSquare size={40} className="mb-3 opacity-30" />
                  <p className="text-sm">发送一条消息开始对话</p>
                </div>
              ) : isDraftStart ? (
                <div className="flex h-full items-start justify-center px-6 pt-[13vh]">
                  <div className="w-full max-w-4xl">
                    <h1 className="mb-12 text-center text-3xl font-medium tracking-normal text-light-text">
                      接下来想做什么？
                    </h1>
                    {renderComposer(true)}
                  </div>
                </div>
              ) : (
                <div className="space-y-4 max-w-4xl mx-auto">
                  {messages.map((msg, i) => {
                    if (msg.role !== 'user' && msg.role !== 'assistant') return null
                    if (msg.role === 'assistant' && !msg.content.trim()) return null
                    const archive = msg.role === 'assistant' ? archiveByAssistantIndex.get(i) : undefined
                    return (
                      <div
                        key={i}
                        className={msg.role === 'user' ? 'flex justify-end' : 'flex'}
                      >
                        <div className={'flex flex-col ' + (msg.role === 'user' ? 'max-w-[78%] items-end' : 'w-full items-start')}>
                          <div
                            className={(
                              msg.role === 'user'
                                ? 'w-full rounded-xl bg-accent-blue px-4 py-2.5 text-white'
                                : 'w-full px-1 py-1 text-light-text'
                            )}
                          >
                            {msg.role === 'user' ? (
                              <div className="text-sm whitespace-pre-wrap break-words">{msg.content}</div>
                            ) : (
                              <>
                                {renderActivityArchive(archive)}
                                <MarkdownContent content={msg.content} />
                              </>
                            )}
                            {msg.timestamp && (
                              <div className={'text-[10px] mt-1 ' + (
                                msg.role === 'user' ? 'text-white/60' : 'text-light-text-secondary'
                              )}>
                                {formatTime(msg.timestamp)}
                              </div>
                            )}
                          </div>
                          {msg.role !== 'user' && (
                            <button
                              onClick={() => {
                                navigator.clipboard.writeText(msg.content)
                                setCopiedIdx(i)
                                setTimeout(() => setCopiedIdx(null), 2000)
                              }}
                              className="flex items-center gap-1 mt-1 px-2 py-0.5 text-[11px] text-light-text-secondary hover:text-light-text rounded transition-colors"
                            >
                              {copiedIdx === i ? <><Check size={12} /> 已复制</> : <><Copy size={12} /> 复制</>}
                            </button>
                          )}
                        </div>
                      </div>
                    )
                  })}
                  {isCurrentSending && (
                    <div className="flex">
                      <div className="w-full min-w-[260px] px-1 py-1">
                        {renderAgentActivity()}
                        {displayedText ? (
                          <div className="text-light-text">
                            <MarkdownContent content={displayedText} />
                            <span className="inline-block w-1.5 h-4 ml-0.5 bg-accent-blue rounded-sm animate-pulse align-text-bottom" />
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 text-sm text-light-text-secondary">
                            <Loader2 size={14} className="animate-spin" />
                            正在思考...
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  <div ref={messagesEndRef} />
                </div>
              )}
            </div>
            {/* Input */}
            {!isDraftStart && (
              <div className="px-5 py-3 shrink-0">
                {renderComposer()}
              </div>
            )}
          </>
        ) : (
          <div className="relative flex-1 flex flex-col items-center justify-center text-light-text-secondary">
            <IconButton
              label="打开菜单"
              onClick={openMobileSidebar}
              size="md"
              surface="plain"
              className="absolute left-3 top-3 lg:hidden"
            >
              <Menu size={20} />
            </IconButton>
            <MessageSquare size={48} className="mb-4 opacity-20" />
            <p className="text-sm mb-4">选择一个对话，或新建对话</p>
            <button
              onClick={() => createDraftSession()}
              className="flex items-center gap-2 rounded-lg bg-accent-blue px-4 py-2 text-sm font-medium text-white hover:bg-accent-blue/90 transition-colors"
            >
              <Plus size={16} />
              新对话
            </button>
          </div>
        )}
      </div>

      <AgentCreatePanel
        open={agentCreateOpen}
        onClose={() => setAgentCreateOpen(false)}
        onCreated={handleAgentCreated}
      />

    </div>
  )
}
