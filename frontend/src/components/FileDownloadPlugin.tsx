/**
 * FileDownloadPlugin — 独立插件，用于在 Markdown 渲染中识别文件路径并渲染为可下载的文件卡片。
 * 图片类型文件会直接内联预览。
 *
 * 使用方式：
 *   import { fileDownloadLinkRenderer, remarkFileLinks } from './FileDownloadPlugin'
 *   // 在 ReactMarkdown remarkPlugins 中加入 remarkFileLinks
 *   // 在 ReactMarkdown components 中：a: fileDownloadLinkRenderer
 *
 * 识别规则：
 *   - workspace/ 或 ~/.openclaw/ 前缀的路径 → 通过 filemanager/download 下载
 *   - 绝对路径（如 /root/.agent-browser/tmp/xxx.png）→ 通过 filemanager/serve 下载/预览
 *   - 纯文本中的路径由 remarkFileLinks remark 插件自动转为链接
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { Download, FileText, FileSpreadsheet, FileImage, File, Loader2, ZoomIn, ZoomOut, X, RotateCcw } from 'lucide-react'
import { getAccessToken } from '../lib/api'

// ---------------------------------------------------------------------------
// 路径识别
// ---------------------------------------------------------------------------

/** 常见文件扩展名 */
const FILE_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'ppt', 'pptx',
  'txt', 'md', 'json', 'xml', 'yaml', 'yml', 'toml',
  'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp',
  'zip', 'tar', 'gz', 'rar', '7z',
  'mp3', 'wav', 'mp4', 'avi', 'mov',
  'py', 'js', 'ts', 'html', 'css',
])

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp'])

/** 匹配 .openclaw 下的相对路径（workspace、media 等） */
const OPENCLAW_PATH_RE =
  /(?:(?:\/[\w.-]+)*\/\.openclaw\/|~\/\.openclaw\/)?(?:workspace(?:-[\w-]+)?|media(?:\/[\w.-]+)*)\/\S+\.\w{1,10}/

/** 匹配绝对路径（以 / 或 ~ 开头，含文件扩展名，如 /tmp/file.png 或 ~/docs/file.pdf） */
const ABSOLUTE_PATH_RE =
  /~?(?:\/[\w._-]+)+\/[\w.\-\u4e00-\u9fff]+\.\w{1,10}/

/** 判断一个 href 是否是可下载的文件路径 */
export function isFilePath(href: string): boolean {
  if (!href) return false
  if (/^https?:\/\//i.test(href)) return false
  // ReactMarkdown 会对中文等字符进行 URL 编码，先解码再匹配
  let decoded = href
  try { decoded = decodeURIComponent(href) } catch { /* keep original */ }
  // workspace 路径
  if (OPENCLAW_PATH_RE.test(decoded)) return true
  // 绝对路径且有已知扩展名
  if (ABSOLUTE_PATH_RE.test(decoded)) {
    const ext = getExt(decoded)
    return FILE_EXTENSIONS.has(ext)
  }
  return false
}

/** 判断路径是否在 .openclaw 下（走 download API）还是绝对路径（走 serve API） */
function isOpenclawPath(href: string): boolean {
  let decoded = href
  try { decoded = decodeURIComponent(href) } catch { /* keep original */ }
  return OPENCLAW_PATH_RE.test(decoded)
}

/**
 * 从路径中提取用于 download API 的相对路径（相对于 ~/.openclaw/）。
 * 支持 workspace/... 和 media/... 等子目录。
 */
function toDownloadPath(href: string): string {
  let decoded = href
  try {
    let prev = ''
    while (decoded !== prev && decoded.includes('%')) {
      prev = decoded
      decoded = decodeURIComponent(decoded)
    }
  } catch { /* ignore */ }
  const match = decoded.match(/(?:workspace(?:-[\w-]+)?|media(?:\/[\w.-]+)*)\/\S+/)
  return match ? match[0] : decoded
}

/**
 * 解码路径，处理多重 URL 编码
 */
function decodePath(href: string): string {
  let decoded = href
  try {
    let prev = ''
    while (decoded !== prev && decoded.includes('%')) {
      prev = decoded
      decoded = decodeURIComponent(decoded)
    }
  } catch { /* ignore */ }
  return decoded
}

/** 从文件名获取扩展名 */
function getExt(filename: string): string {
  const dot = filename.lastIndexOf('.')
  return dot >= 0 ? filename.slice(dot + 1).toLowerCase() : ''
}

/** 根据扩展名选择图标 */
function FileIcon({ ext }: { ext: string }) {
  if (['xls', 'xlsx', 'csv'].includes(ext))
    return <FileSpreadsheet size={18} className="text-green-400" />
  if (IMAGE_EXTENSIONS.has(ext))
    return <FileImage size={18} className="text-purple-400" />
  if (['doc', 'docx', 'pdf', 'txt', 'md'].includes(ext))
    return <FileText size={18} className="text-blue-400" />
  return <File size={18} className="text-gray-400" />
}

/** 构建下载/预览 URL */
function buildFileUrl(href: string, inline?: boolean): string {
  if (isOpenclawPath(href)) {
    const cleanPath = toDownloadPath(href)
    return `/api/openclaw/filemanager/download?path=${encodeURIComponent(cleanPath)}`
  }
  // 绝对路径 → serve API
  const decoded = decodePath(href)
  let url = `/api/openclaw/filemanager/serve?path=${encodeURIComponent(decoded)}`
  if (inline) url += '&inline=1'
  return url
}

// ---------------------------------------------------------------------------
// 图片灯箱组件（全屏查看、缩放、拖拽）
// ---------------------------------------------------------------------------

const MIN_SCALE = 0.5
const MAX_SCALE = 5
const ZOOM_STEP = 0.3

function ImageLightbox({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  const [scale, setScale] = useState(1)
  const [offset, setOffset] = useState({ x: 0, y: 0 })
  const dragging = useRef(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const offsetStart = useRef({ x: 0, y: 0 })
  const offsetRef = useRef({ x: 0, y: 0 })

  const clampScale = (s: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s))

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.stopPropagation()
    setScale(prev => clampScale(prev + (e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP)))
  }, [])

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0) return
    dragging.current = true
    dragStart.current = { x: e.clientX, y: e.clientY }
    offsetStart.current = { ...offsetRef.current }
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }, [])

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return
    const next = {
      x: offsetStart.current.x + e.clientX - dragStart.current.x,
      y: offsetStart.current.y + e.clientY - dragStart.current.y,
    }
    offsetRef.current = next
    setOffset(next)
  }, [])

  const handlePointerUp = useCallback(() => { dragging.current = false }, [])

  const resetView = useCallback(() => {
    const zero = { x: 0, y: 0 }
    offsetRef.current = zero
    setScale(1)
    setOffset(zero)
  }, [])

  // ESC to close
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Prevent body scroll while lightbox is open
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      {/* Toolbar */}
      <div className="absolute top-4 right-4 flex items-center gap-1 z-10">
        <button onClick={() => setScale(s => clampScale(s + ZOOM_STEP))}
          className="p-2 rounded-lg bg-dark-bg/80 text-dark-text hover:text-accent-blue transition-colors" title="放大">
          <ZoomIn size={18} />
        </button>
        <button onClick={() => setScale(s => clampScale(s - ZOOM_STEP))}
          className="p-2 rounded-lg bg-dark-bg/80 text-dark-text hover:text-accent-blue transition-colors" title="缩小">
          <ZoomOut size={18} />
        </button>
        <button onClick={resetView}
          className="p-2 rounded-lg bg-dark-bg/80 text-dark-text hover:text-accent-blue transition-colors" title="重置">
          <RotateCcw size={18} />
        </button>
        <button onClick={onClose}
          className="p-2 rounded-lg bg-dark-bg/80 text-dark-text hover:text-accent-red transition-colors" title="关闭">
          <X size={18} />
        </button>
      </div>
      {/* Scale indicator */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-xs text-dark-text-secondary bg-dark-bg/80 px-3 py-1 rounded-full">
        {Math.round(scale * 100)}%
      </div>
      {/* Image */}
      <img
        src={src}
        alt={alt}
        draggable={false}
        className="select-none"
        style={{
          transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
          cursor: dragging.current ? 'grabbing' : 'grab',
          maxWidth: '90vw',
          maxHeight: '90vh',
          objectFit: 'contain',
        }}
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// 图片预览组件
// ---------------------------------------------------------------------------

function ImagePreviewCard({ href, children }: { href: string; children: React.ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const decoded = decodePath(href)
  let filename = decoded.split('/').pop() || decoded
  try { filename = decodeURIComponent(filename) } catch { /* ignore */ }
  const ext = getExt(filename)

  const token = getAccessToken()
  const previewUrl = buildFileUrl(href, true) + (token ? `&token=${encodeURIComponent(token)}` : '')

  const handleDownload = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (downloading) return
    setDownloading(true)
    try {
      const url = buildFileUrl(href)
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(url, { headers })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const blobUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = filename
      document.body.appendChild(a)
      a.click()
      setTimeout(() => {
        URL.revokeObjectURL(blobUrl)
        document.body.removeChild(a)
      }, 1000)
    } catch {
      // fallback: open in new tab
      window.open(previewUrl, '_blank')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="my-2 rounded-lg border border-dark-border bg-dark-bg/60 overflow-hidden inline-block max-w-md">
      {!error && (
        <div className="relative">
          {loading && (
            <div className="flex items-center justify-center py-8 px-12">
              <Loader2 size={20} className="animate-spin text-accent-blue" />
            </div>
          )}
          <img
            src={previewUrl}
            alt={filename}
            className={`max-w-full max-h-[300px] object-contain cursor-zoom-in ${loading ? 'hidden' : 'block'}`}
            onClick={() => setLightboxOpen(true)}
            onLoad={() => setLoading(false)}
            onError={() => { setLoading(false); setError(true) }}
          />
        </div>
      )}
      <button
        onClick={handleDownload}
        disabled={downloading}
        className="flex items-center gap-2 w-full px-3 py-2 border-t border-dark-border hover:bg-dark-bg hover:border-accent-blue/40 transition-all cursor-pointer group disabled:opacity-60"
        title={decoded}
      >
        <FileIcon ext={ext} />
        <span className="text-xs text-dark-text group-hover:text-accent-blue transition-colors truncate max-w-[200px]" title={decoded}>
          {typeof children === 'string' ? children : filename}
        </span>
        {downloading ? (
          <Loader2 size={14} className="ml-auto animate-spin text-accent-blue shrink-0" />
        ) : (
          <Download size={14} className="ml-auto text-dark-text-secondary group-hover:text-accent-blue transition-colors shrink-0" />
        )}
      </button>
      {lightboxOpen && <ImageLightbox src={previewUrl} alt={filename} onClose={() => setLightboxOpen(false)} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 下载卡片组件
// ---------------------------------------------------------------------------

function FileDownloadCard({ href, children }: { href: string; children: React.ReactNode }) {
  const [downloading, setDownloading] = useState(false)
  const [dlError, setDlError] = useState('')
  const decoded = decodePath(href)
  let filename = decoded.split('/').pop() || decoded
  try { filename = decodeURIComponent(filename) } catch { /* ignore */ }
  const ext = getExt(filename)

  const handleDownload = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (downloading) return

    setDownloading(true)
    setDlError('')
    try {
      const token = getAccessToken()
      const url = buildFileUrl(href)
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`

      const res = await fetch(url, { headers })
      if (!res.ok) {
        const detail = await res.text().catch(() => '')
        throw new Error(detail || `HTTP ${res.status}`)
      }

      const blob = await res.blob()
      const blobUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = filename
      document.body.appendChild(a)
      a.click()
      setTimeout(() => {
        URL.revokeObjectURL(blobUrl)
        document.body.removeChild(a)
      }, 1000)
    } catch (err: any) {
      console.error('文件下载失败:', err)
      setDlError('下载失败')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <button
      onClick={handleDownload}
      disabled={downloading}
      title={decoded}
      className="inline-flex items-center gap-2 my-1 px-3 py-2 rounded-lg border border-dark-border bg-dark-bg/60 hover:bg-dark-bg hover:border-accent-blue/40 transition-all cursor-pointer group disabled:opacity-60"
    >
      <FileIcon ext={ext} />
      <span className="text-xs text-dark-text group-hover:text-accent-blue transition-colors truncate max-w-[200px]">
        {typeof children === 'string' ? children : filename}
      </span>
      {downloading ? (
        <Loader2 size={14} className="animate-spin text-accent-blue shrink-0" />
      ) : dlError ? (
        <span className="text-[10px] text-accent-red shrink-0">{dlError}</span>
      ) : (
        <Download size={14} className="text-dark-text-secondary group-hover:text-accent-blue transition-colors shrink-0" />
      )}
    </button>
  )
}

// ---------------------------------------------------------------------------
// 导出：ReactMarkdown 的 a 渲染器
// ---------------------------------------------------------------------------

export function fileDownloadLinkRenderer({
  href,
  children,
}: {
  href?: string
  children?: React.ReactNode
}) {
  if (href && isFilePath(href)) {
    const ext = getExt(decodePath(href))
    if (IMAGE_EXTENSIONS.has(ext)) {
      return <ImagePreviewCard href={href}>{children}</ImagePreviewCard>
    }
    return <FileDownloadCard href={href}>{children}</FileDownloadCard>
  }

  return (
    <a href={href} target="_blank" rel="noreferrer" className="text-accent-blue hover:underline">
      {children}
    </a>
  )
}

// ---------------------------------------------------------------------------
// 导出：remark 插件 — 自动将纯文本中的文件路径转为链接
// ---------------------------------------------------------------------------

/**
 * remark 插件：扫描文本节点，将匹配文件路径模式的纯文本自动转为 markdown 链接。
 */
export function remarkFileLinks() {
  // 匹配 .openclaw 下的路径（workspace、media 等）和绝对路径
  const GLOBAL_RE =
    /(?:(?:\/[\w.-]+)*\/\.openclaw\/|~\/\.openclaw\/)?(?:workspace(?:-[\w-]+)?|media(?:\/[\w.-]+)*)\/[\w.\/\-\u4e00-\u9fff]+\.\w{1,10}|~?(?:\/[\w._-]+)+\/[\w.\-\u4e00-\u9fff]+\.\w{1,10}/g

  return (tree: any) => {
    // 处理普通文本节点
    visit(tree, 'text', (node: any, index: number | null, parent: any) => {
      if (!parent || index === null) return
      if (parent.type === 'link') return

      const value: string = node.value
      GLOBAL_RE.lastIndex = 0
      const matches = [...value.matchAll(GLOBAL_RE)]
      if (matches.length === 0) return

      const children: any[] = []
      let lastEnd = 0

      for (const match of matches) {
        const start = match.index!
        const end = start + match[0].length
        const filePath = match[0]
        const ext = getExt(filePath)

        if (!FILE_EXTENSIONS.has(ext)) continue

        if (start > lastEnd) {
          children.push({ type: 'text', value: value.slice(lastEnd, start) })
        }

        const filename = filePath.split('/').pop() || filePath
        children.push({
          type: 'link',
          url: filePath,
          children: [{ type: 'text', value: filename }],
        })

        lastEnd = end
      }

      if (children.length === 0) return

      if (lastEnd < value.length) {
        children.push({ type: 'text', value: value.slice(lastEnd) })
      }

      parent.children.splice(index, 1, ...children)
    })

    // 处理行内代码节点（AI 经常用反引号包裹路径）
    visit(tree, 'inlineCode', (node: any, index: number | null, parent: any) => {
      if (!parent || index === null) return
      const value: string = node.value
      GLOBAL_RE.lastIndex = 0
      const match = GLOBAL_RE.exec(value)
      if (!match) return
      const filePath = match[0]
      const ext = getExt(filePath)
      if (!FILE_EXTENSIONS.has(ext)) return
      const filename = filePath.split('/').pop() || filePath
      parent.children.splice(index, 1, {
        type: 'link',
        url: filePath,
        children: [{ type: 'text', value: filename }],
      })
    })

    // 处理代码块节点（AI 有时用 ``` 代码块包裹路径）
    visit(tree, 'code', (node: any, index: number | null, parent: any) => {
      if (!parent || index === null) return
      const value: string = node.value?.trim()
      if (!value) return
      GLOBAL_RE.lastIndex = 0
      const match = GLOBAL_RE.exec(value)
      if (!match) return
      const filePath = match[0]
      const ext = getExt(filePath)
      if (!FILE_EXTENSIONS.has(ext)) return
      // 只有当代码块内容基本就是一个路径时才替换（避免误匹配大段代码）
      if (value.length > filePath.length + 20) return
      const filename = filePath.split('/').pop() || filePath
      parent.children.splice(index, 1, {
        type: 'paragraph',
        children: [{
          type: 'link',
          url: filePath,
          children: [{ type: 'text', value: filename }],
        }],
      })
    })
  }
}

// ---------------------------------------------------------------------------
// Minimal AST visitor (避免额外依赖 unist-util-visit)
// ---------------------------------------------------------------------------

function visit(tree: any, type: string, fn: (node: any, index: number | null, parent: any) => void) {
  function walker(node: any, index: number | null, parent: any) {
    if (node.type === type) {
      fn(node, index, parent)
    }
    if (node.children) {
      for (let i = node.children.length - 1; i >= 0; i--) {
        walker(node.children[i], i, node)
      }
    }
  }
  walker(tree, null, null)
}
