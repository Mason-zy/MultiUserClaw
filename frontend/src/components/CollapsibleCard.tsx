import { useState } from 'react'
import { ChevronRight, Wrench, Brain, Terminal, Eye, FileText, AlertCircle, CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import type { ChatMessage, ToolCallInfo } from '../lib/api'

/** Friendly tool name mapping */
function toolDisplayName(name: string): string {
  switch (name) {
    case 'skill_view': return '加载技能'
    case 'terminal': return '执行命令'
    case 'run_command': return '执行命令'
    case 'view_file': return '查看文件'
    case 'write_file': return '写入文件'
    case 'edit_file': return '编辑文件'
    case 'skills_list': return '列出技能'
    case 'web_search': return '网络搜索'
    case 'browser_navigate': return '浏览网页'
    default: return name
  }
}

function toolIcon(name: string) {
  switch (name) {
    case 'skill_view':
    case 'skills_list':
      return <FileText size={12} />
    case 'terminal':
    case 'run_command':
      return <Terminal size={12} />
    case 'view_file':
    case 'write_file':
    case 'edit_file':
      return <Eye size={12} />
    default:
      return <Wrench size={12} />
  }
}

/** Extract a short summary from tool result JSON */
function toolResultSummary(content: string): { status: 'success' | 'error' | 'neutral'; summary: string } {
  try {
    const parsed = JSON.parse(content)
    // skill_view result
    if (parsed.success === true && parsed.name) {
      return { status: 'success', summary: `已加载: ${parsed.name}` }
    }
    if (parsed.success === false) {
      return { status: 'error', summary: parsed.error || '加载失败' }
    }
    // terminal result
    if ('exit_code' in parsed) {
      if (parsed.status === 'blocked') {
        return { status: 'error', summary: '命令被拒绝' }
      }
      if (parsed.exit_code === 0) {
        const output = (parsed.output || '').trim()
        return { status: 'success', summary: output ? output.split('\n')[0].slice(0, 80) : '执行成功' }
      }
      const errMsg = (parsed.error || parsed.output || '').trim().split('\n').pop()?.slice(0, 80) || '执行失败'
      return { status: 'error', summary: errMsg }
    }
    // view_file result
    if (parsed.content) {
      return { status: 'success', summary: '文件内容已读取' }
    }
    return { status: 'neutral', summary: content.slice(0, 80) }
  } catch {
    return { status: 'neutral', summary: content.slice(0, 80) }
  }
}

function StatusIcon({ status }: { status: 'success' | 'error' | 'neutral' }) {
  switch (status) {
    case 'success': return <CheckCircle2 size={12} className="text-green-400" />
    case 'error': return <XCircle size={12} className="text-red-400" />
    default: return <AlertCircle size={12} className="text-dark-text-secondary" />
  }
}

/** A group of tool calls: assistant message with tool_calls + corresponding tool result messages */
export interface ToolCallGroup {
  assistant: ChatMessage
  toolResults: ChatMessage[]
}

/** Group consecutive assistant(tool_calls) + tool messages into ToolCallGroups */
export function groupToolCalls(messages: ChatMessage[]): (ChatMessage | ToolCallGroup)[] {
  const result: (ChatMessage | ToolCallGroup)[] = []
  let i = 0
  while (i < messages.length) {
    const msg = messages[i]
    if (msg.role === 'assistant' && msg.tool_calls?.length) {
      const group: ToolCallGroup = { assistant: msg, toolResults: [] }
      i++
      while (i < messages.length && messages[i].role === 'tool') {
        group.toolResults.push(messages[i])
        i++
      }
      result.push(group)
    } else if (msg.role === 'tool') {
      // Orphan tool message (shouldn't happen normally)
      const group: ToolCallGroup = {
        assistant: { role: 'assistant', content: '', tool_calls: [] },
        toolResults: [msg],
      }
      result.push(group)
      i++
    } else {
      result.push(msg)
      i++
    }
  }
  return result
}

/** Collapsible card for a group of tool calls */
export function ToolCallGroupCard({ group }: { group: ToolCallGroup }) {
  const [expanded, setExpanded] = useState(false)
  const toolCalls = group.assistant.tool_calls || []
  const toolNames = toolCalls.map(tc => tc.function?.name || 'unknown')
  const uniqueNames = [...new Set(toolNames)]
  const label = uniqueNames.map(n => toolDisplayName(n)).join('、')

  return (
    <div className="my-1.5 max-w-3xl">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-dark-card/60 border border-dark-border/50 hover:bg-dark-card-hover transition-colors text-xs text-dark-text-secondary w-full text-left"
      >
        <ChevronRight
          size={12}
          className={`transition-transform shrink-0 ${expanded ? 'rotate-90' : ''}`}
        />
        <Wrench size={12} className="text-accent-blue shrink-0" />
        <span className="truncate">
          {group.assistant.content?.trim()
            ? group.assistant.content.trim().slice(0, 60)
            : `使用工具: ${label}`}
        </span>
        <span className="ml-auto text-[10px] text-dark-text-secondary/60 shrink-0">
          {toolCalls.length} 次调用
        </span>
      </button>
      {expanded && (
        <div className="mt-1 ml-4 space-y-1 border-l-2 border-dark-border/30 pl-3">
          {toolCalls.map((tc, idx) => {
            const fnName = tc.function?.name || 'unknown'
            const matchingResult = group.toolResults.find(r => r.tool_call_id === tc.id)
            const resultInfo = matchingResult
              ? toolResultSummary(matchingResult.content)
              : null

            return (
              <ToolCallDetail
                key={tc.id || idx}
                toolCall={tc}
                fnName={fnName}
                resultContent={matchingResult?.content}
                resultInfo={resultInfo}
              />
            )
          })}
        </div>
      )}
    </div>
  )
}

function ToolCallDetail({
  toolCall,
  fnName,
  resultContent,
  resultInfo,
}: {
  toolCall: ToolCallInfo
  fnName: string
  resultContent?: string
  resultInfo: { status: 'success' | 'error' | 'neutral'; summary: string } | null
}) {
  const [detailExpanded, setDetailExpanded] = useState(false)

  return (
    <div className="text-xs">
      <button
        type="button"
        onClick={() => setDetailExpanded(!detailExpanded)}
        className="flex items-center gap-1.5 py-1 text-dark-text-secondary hover:text-dark-text transition-colors w-full text-left"
      >
        <ChevronRight
          size={10}
          className={`transition-transform shrink-0 ${detailExpanded ? 'rotate-90' : ''}`}
        />
        {toolIcon(fnName)}
        <span>{toolDisplayName(fnName)}</span>
        {resultInfo && (
          <>
            <StatusIcon status={resultInfo.status} />
            <span className="truncate text-[10px] text-dark-text-secondary/70">
              {resultInfo.summary}
            </span>
          </>
        )}
      </button>
      {detailExpanded && (
        <div className="ml-5 mt-1 space-y-1">
          {toolCall.function?.arguments && (
            <pre className="text-[10px] bg-dark-bg/50 rounded p-2 overflow-x-auto max-h-40 text-dark-text-secondary">
              {formatArgs(toolCall.function.arguments)}
            </pre>
          )}
          {resultContent && (
            <pre className="text-[10px] bg-dark-bg/50 rounded p-2 overflow-x-auto max-h-60 text-dark-text-secondary">
              {formatResultContent(resultContent)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

function formatArgs(args: string): string {
  try {
    const parsed = JSON.parse(args)
    if (parsed.command) return parsed.command
    return JSON.stringify(parsed, null, 2)
  } catch {
    return args
  }
}

function formatResultContent(content: string): string {
  try {
    const parsed = JSON.parse(content)
    if (parsed.output !== undefined) return parsed.output || '(empty output)'
    if (parsed.content !== undefined) {
      const c = parsed.content
      return typeof c === 'string' ? c.slice(0, 2000) : JSON.stringify(c, null, 2).slice(0, 2000)
    }
    return JSON.stringify(parsed, null, 2).slice(0, 2000)
  } catch {
    return content.slice(0, 2000)
  }
}

/** Live tool call item shown during SSE streaming */
export interface LiveToolCallInfo {
  id: string
  tool: string
  preview?: string
  status: 'running' | 'done' | 'error'
  duration?: number
}

/** Card showing real-time tool call progress during streaming */
export function LiveToolCallsCard({ tools }: { tools: LiveToolCallInfo[] }) {
  if (tools.length === 0) return null

  return (
    <div className="my-1.5 max-w-3xl space-y-1">
      {tools.map(tc => (
        <div
          key={tc.id}
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-dark-card/60 border border-dark-border/50 text-xs text-dark-text-secondary"
        >
          {tc.status === 'running' ? (
            <Loader2 size={12} className="animate-spin text-accent-blue shrink-0" />
          ) : tc.status === 'error' ? (
            <XCircle size={12} className="text-red-400 shrink-0" />
          ) : (
            <CheckCircle2 size={12} className="text-green-400 shrink-0" />
          )}
          {toolIcon(tc.tool)}
          <span>{toolDisplayName(tc.tool)}</span>
          {tc.preview && (
            <span className="truncate text-[10px] text-dark-text-secondary/70 ml-1">
              {tc.preview.slice(0, 60)}
            </span>
          )}
          {tc.status === 'running' && (
            <span className="ml-auto text-[10px] text-accent-blue/70">执行中...</span>
          )}
          {tc.status === 'done' && tc.duration != null && (
            <span className="ml-auto text-[10px] text-dark-text-secondary/50">
              {tc.duration.toFixed(1)}s
            </span>
          )}
        </div>
      ))}
    </div>
  )
}

/** Live reasoning card shown during SSE streaming (non-collapsible, always visible) */
export function LiveReasoningCard({ content }: { content: string }) {
  if (!content.trim()) return null

  return (
    <div className="my-1.5 max-w-3xl">
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-purple-500/5 border border-purple-500/20 text-xs text-purple-300/80">
        <Loader2 size={12} className="animate-spin shrink-0" />
        <Brain size={12} className="shrink-0" />
        <span>思考中...</span>
      </div>
      <div className="mt-1 ml-4 pl-3 border-l-2 border-purple-500/20">
        <pre className="text-[11px] text-dark-text-secondary whitespace-pre-wrap break-words max-h-40 overflow-y-auto p-2">
          {content}
        </pre>
      </div>
    </div>
  )
}

/** Collapsible card for reasoning/thinking content */
export function ThinkingCard({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false)
  if (!content.trim()) return null

  return (
    <div className="my-1.5 max-w-3xl">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-purple-500/5 border border-purple-500/20 hover:bg-purple-500/10 transition-colors text-xs text-purple-300/80 w-full text-left"
      >
        <ChevronRight
          size={12}
          className={`transition-transform shrink-0 ${expanded ? 'rotate-90' : ''}`}
        />
        <Brain size={12} className="shrink-0" />
        <span>思考过程</span>
      </button>
      {expanded && (
        <div className="mt-1 ml-4 pl-3 border-l-2 border-purple-500/20">
          <pre className="text-[11px] text-dark-text-secondary whitespace-pre-wrap break-words max-h-80 overflow-y-auto p-2">
            {content}
          </pre>
        </div>
      )}
    </div>
  )
}
