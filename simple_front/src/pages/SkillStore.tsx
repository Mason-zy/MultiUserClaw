import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { useOutletContext } from 'react-router-dom'
import {
  ArrowLeft,
  Bot,
  Check,
  Download,
  FileText,
  GitBranch,
  Inbox,
  Loader2,
  Package,
  RefreshCw,
  Save,
  Search,
  Sparkles,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import ClearableInput from '../components/ui/ClearableInput.tsx'
import IconButton from '../components/ui/IconButton.tsx'
import Popconfirm from '../components/ui/Popconfirm.tsx'
import { useToast } from '../components/ui/Toast.tsx'
import type { LayoutOutletContext } from '../components/Layout.tsx'
import {
  browseFiles,
  deleteSkill,
  downloadSkill,
  getSkillFile,
  installGitSkills,
  installSkillFromSearch,
  listSkillFiles,
  listSkillScopes,
  listSkills,
  scanGitSkills,
  searchSkills,
  uploadSkillZip,
  writeManagedFile,
  writeSkillFile,
} from '../lib/api.ts'
import type { BrowseFileResult, GitScanResult, SkillFileInfo, SkillInfo, SkillScope, SkillSearchResult } from '../lib/api.ts'

const skillsCacheTtlMs = 30_000
const skillsCacheStorageKey = 'openclaw_simple_front_skills_cache_v3'
type SkillsCache = { scopes: SkillScope[]; skills: SkillInfo[]; at: number }
let skillsCache: SkillsCache | null = null

const builtinAgentNames: Record<string, string> = {
  main: '默认',
  manager: '经理',
  programmer: '程序员',
  researcher: '研究员',
  hr: 'HR',
  doctor: '医生',
}

function readStoredSkillsCache(): SkillsCache | null {
  if (skillsCache) return skillsCache
  try {
    const raw = sessionStorage.getItem(skillsCacheStorageKey)
    if (!raw) return null
    const parsed = JSON.parse(raw) as SkillsCache | null
    if (!parsed || !Array.isArray(parsed.scopes) || !Array.isArray(parsed.skills) || typeof parsed.at !== 'number') return null
    skillsCache = parsed
    return parsed
  } catch {
    return null
  }
}

function writeSkillsCache(cache: SkillsCache): void {
  skillsCache = cache
  try {
    sessionStorage.setItem(skillsCacheStorageKey, JSON.stringify(cache))
  } catch {
    // Best-effort UI cache only; keep the in-memory cache even if storage is unavailable.
  }
}

function clearSkillsCache(): void {
  skillsCache = null
  try {
    sessionStorage.removeItem(skillsCacheStorageKey)
  } catch {
    // Ignore storage failures.
  }
}

function getFreshSkillsCache(): SkillsCache | null {
  const cache = readStoredSkillsCache()
  if (!cache || Date.now() - cache.at >= skillsCacheTtlMs) return null
  return cache
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function scopeRank(scope: SkillScope): number {
  if (scope.type === 'global') return 0
  if (scope.type === 'builtin') return 2
  return 1
}

function getAgentDisplayName(agent: { id: string; name?: string | null; identity?: { name?: string } } | undefined, agentId: string): string {
  return agent?.identity?.name || agent?.name || builtinAgentNames[agentId] || agentId
}

function legacySkillFilePath(skill: SkillInfo, filePath: string): string | null {
  const normalized = skill.path.replace(/\\/g, '/')
  const marker = '/.openclaw/'
  const markerIndex = normalized.toLowerCase().indexOf(marker)
  if (markerIndex < 0) return null
  const skillRoot = normalized.slice(0, normalized.length - 'SKILL.md'.length).replace(/\/+$/, '')
  const target = `${skillRoot}/${filePath}`.replace(/\\/g, '/')
  const relative = target.slice(markerIndex + marker.length)
  return relative || null
}

function SkillSkeleton() {
  return (
    <div className="min-h-0 flex-1 space-y-2 overflow-hidden" aria-hidden="true">
      {Array.from({ length: 7 }).map((_, index) => (
        <div key={index} className="rounded-lg border border-light-border bg-light-card p-3">
          <div className="flex items-center gap-3">
            <span className="skeleton-shimmer h-9 w-9 rounded-lg" />
            <span className="skeleton-shimmer h-4 flex-1 rounded-full" />
            <span className="skeleton-shimmer h-4 w-16 rounded-full" />
          </div>
        </div>
      ))}
    </div>
  )
}

function SkillFileSkeleton() {
  return (
    <div className="min-h-0 flex-1 overflow-hidden" aria-hidden="true">
      <div className="space-y-0">
        {Array.from({ length: 8 }).map((_, index) => (
          <div key={index} className="flex items-center gap-3 border-b border-light-border/70 px-4 py-3">
            <span className="skeleton-shimmer h-5 w-5 shrink-0 rounded-md" />
            <span className="min-w-0 flex-1 space-y-2">
              <span className="skeleton-shimmer block h-3.5 w-4/5 rounded-full" />
              <span className="skeleton-shimmer block h-3 w-16 rounded-full" />
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function gitErrorMessage(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err || '')
  if (/Repository not found|not found/i.test(raw)) {
    return 'Git 仓库不存在或地址不可访问，请检查地址是否正确。例如 .git 后面不要追加多余字符。'
  }
  if (/Failed to clone repo|failed to clone|Could not connect|timed out|unable to access/i.test(raw)) {
    return '无法克隆这个 Git 仓库，请检查仓库地址、网络连接，或改用可访问的 Gitee/内网镜像。'
  }
  return raw || 'Git 仓库扫描失败，请检查地址后重试。'
}

export default function SkillStore() {
  const { agents, openMobileSidebar } = useOutletContext<LayoutOutletContext>()
  const [scopes, setScopes] = useState<SkillScope[]>(() => readStoredSkillsCache()?.scopes || [])
  const [selectedScopeId, setSelectedScopeId] = useState('global')
  const [skills, setSkills] = useState<SkillInfo[]>(() => readStoredSkillsCache()?.skills || [])
  const [loading, setLoading] = useState(() => !readStoredSkillsCache())
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchResults, setSearchResults] = useState<SkillSearchResult[]>([])
  const [installing, setInstalling] = useState('')
  const [uploading, setUploading] = useState(false)
  const [activeModal, setActiveModal] = useState<'search' | 'git' | null>(null)
  const [gitUrl, setGitUrl] = useState('')
  const [gitScanning, setGitScanning] = useState(false)
  const [gitScan, setGitScan] = useState<GitScanResult | null>(null)
  const [gitSelected, setGitSelected] = useState<Set<string>>(new Set())
  const [gitInstalling, setGitInstalling] = useState(false)
  const [selectedSkill, setSelectedSkill] = useState<SkillInfo | null>(null)
  const [skillFiles, setSkillFiles] = useState<SkillFileInfo[]>([])
  const [filesLoading, setFilesLoading] = useState(false)
  const [editorFile, setEditorFile] = useState<{ skill: SkillInfo; path: string; name: string; content: string; originalContent: string } | null>(null)
  const [editorLoading, setEditorLoading] = useState(false)
  const [editorSaving, setEditorSaving] = useState(false)
  const uploadRef = useRef<HTMLInputElement>(null)
  const filesRequestSeq = useRef(0)
  const toast = useToast()

  const sortedScopes = useMemo(
    () => [...scopes].sort((a, b) => scopeRank(a) - scopeRank(b) || a.label.localeCompare(b.label)),
    [scopes],
  )
  const selectedScope = scopes.find(scope => scope.id === selectedScopeId) || scopes[0]
  const filteredSkills = useMemo(() => {
    if (!selectedScope) return []
    return skills.filter(skill => skill.scope === selectedScope.id)
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [selectedScope, skills])
  const canInstallToSelectedScope = Boolean(selectedScope?.writable)
  const editorDirty = editorFile ? editorFile.content !== editorFile.originalContent : false

  const normalizeSkillScopes = useCallback((items: SkillScope[]): SkillScope[] => {
    return items.map(scope => {
      if (scope.type === 'global') {
        return { ...scope, label: '全局技能' }
      }
      if (scope.type === 'builtin') {
        return { ...scope, label: '内置技能' }
      }
      const agentId = scope.agentId || scope.id.replace(/^agent:/, '')
      const agent = agents.find(item => item.id === agentId)
      return {
        ...scope,
        agentId,
        label: `${getAgentDisplayName(agent, agentId)} 的技能`,
      }
    })
  }, [agents])

  const fallbackScopes = useMemo<SkillScope[]>(() => normalizeSkillScopes([
      {
        id: 'global',
        type: 'global',
        label: '全局技能',
        path: '~/.openclaw/skills',
        writable: true,
      },
      {
        id: 'builtin',
        type: 'builtin',
        label: '内置技能',
        path: 'openclaw/skills',
        writable: false,
      },
      ...agents
        .filter(agent => agent.id)
        .map(agent => ({
          id: `agent:${agent.id}`,
          type: 'agent' as const,
          agentId: agent.id,
          label: `${getAgentDisplayName(agent, agent.id)} 的技能`,
          path: `profiles/${agent.id}/skills`,
          writable: true,
        })),
    ]),
    [agents, normalizeSkillScopes],
  )

  const normalizeLegacySkill = useCallback((skill: SkillInfo, nextScopes: SkillScope[]): SkillInfo => {
    const source = skill.scopeType || (skill.source === 'builtin' ? 'builtin' : skill.source === 'workspace' ? 'agent' : 'global')
    const scope = nextScopes.find(item => item.id === skill.scope)
      || (source === 'agent'
        ? nextScopes.find(item => item.id === `agent:${skill.agentId || 'main'}`) || nextScopes.find(item => item.type === 'agent')
        : nextScopes.find(item => item.type === source))
    const scopeType = scope?.type || source
    return {
      ...skill,
      scope: scope?.id || skill.scope || source,
      scopeType,
      scopeLabel: scope?.label || (scopeType === 'builtin' ? '内置技能' : scopeType === 'agent' ? '默认的技能' : '全局技能'),
      agentId: scopeType === 'agent' ? scope?.agentId || skill.agentId || 'main' : undefined,
      writable: scope?.writable ?? scopeType !== 'builtin',
      dirPath: skill.dirPath || skill.path.replace(/[\\/]+SKILL\.md$/, ''),
    }
  }, [])

  const readSkills = useCallback(async (options: { force?: boolean } = {}) => {
    const freshCache = getFreshSkillsCache()
    if (!options.force && freshCache) {
      setScopes(freshCache.scopes)
      setSkills(freshCache.skills)
      setLoading(false)
      if (!freshCache.scopes.some(scope => scope.id === selectedScopeId)) {
        setSelectedScopeId(freshCache.scopes.find(scope => scope.type === 'global')?.id || freshCache.scopes[0]?.id || '')
      }
      return
    }

    const cached = readStoredSkillsCache()
    if (!cached) setLoading(true)
    try {
      const [scopeSettled, skillResult] = await Promise.all([
        listSkillScopes().then(
          value => ({ ok: true as const, value }),
          err => ({ ok: false as const, error: err }),
        ),
        listSkills().catch(async () => listSkills(undefined)),
      ])
      const scopeResult = normalizeSkillScopes(scopeSettled.ok ? scopeSettled.value : fallbackScopes)
      const normalizedSkills = skillResult.map(skill => normalizeLegacySkill(skill, scopeResult))
      writeSkillsCache({ scopes: scopeResult, skills: normalizedSkills, at: Date.now() })
      setScopes(scopeResult)
      setSkills(normalizedSkills)
      if (!scopeResult.some(scope => scope.id === selectedScopeId)) {
        setSelectedScopeId(scopeResult.find(scope => scope.type === 'global')?.id || scopeResult[0]?.id || '')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '加载技能失败')
    } finally {
      setLoading(false)
    }
  }, [fallbackScopes, normalizeLegacySkill, normalizeSkillScopes, selectedScopeId])

  const refresh = useCallback(async () => {
    clearSkillsCache()
    await readSkills({ force: true })
  }, [readSkills])

  const refreshScopeSkills = useCallback(async (scope: SkillScope): Promise<SkillInfo[]> => {
    const scopeResult = normalizeSkillScopes(scopes.length > 0 ? scopes : fallbackScopes)
    const nextScopeSkills = (await listSkills(scope)).map(skill => normalizeLegacySkill(skill, scopeResult))
    setSkills(current => {
      const nextSkills = [
        ...current.filter(skill => skill.scope !== scope.id),
        ...nextScopeSkills,
      ]
      writeSkillsCache({
        scopes: scopeResult,
        skills: nextSkills,
        at: Date.now(),
      })
      return nextSkills
    })
    return nextScopeSkills
  }, [fallbackScopes, normalizeLegacySkill, normalizeSkillScopes, scopes])

  useEffect(() => {
    void readSkills()
  }, [readSkills])

  const showErrorMessage = useCallback((text: string) => toast.error(text), [toast])

  const refreshSkillFiles = useCallback(async (skill: SkillInfo) => {
    const requestId = ++filesRequestSeq.current
    setFilesLoading(true)
    try {
      const result = await listSkillFiles(skill)
      if (requestId !== filesRequestSeq.current) return
      setSkillFiles(result.files)
    } catch (err) {
      if (requestId !== filesRequestSeq.current) return
      setSkillFiles([])
      toast.error(err instanceof Error ? err.message : '加载技能文件失败')
    } finally {
      if (requestId === filesRequestSeq.current) setFilesLoading(false)
    }
  }, [])

  const selectSkill = (skill: SkillInfo) => {
    setSelectedSkill(skill)
    setSkillFiles([])
    void refreshSkillFiles(skill)
  }

  const selectScope = (scopeId: string) => {
    setSelectedScopeId(scopeId)
    setSelectedSkill(null)
    setSkillFiles([])
    setEditorFile(null)
  }

  const handleSearch = async () => {
    if (!query.trim()) return
    setSearching(true)
    try {
      const result = await searchSkills(query.trim(), 12)
      setSearchResults(result.results || [])
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '搜索失败')
    } finally {
      setSearching(false)
    }
  }

  const installWithRefresh = async (key: string, run: () => Promise<unknown>) => {
    if (!selectedScope) return
    const targetScope = selectedScope
    setInstalling(key)
    try {
      const result = await run()
      await refreshScopeSkills(targetScope)
      const installedName = result && typeof result === 'object' && 'name' in result && typeof result.name === 'string'
        ? result.name
        : key
      toast.success(`已安装 ${installedName} 到 ${targetScope.label}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '安装失败')
    } finally {
      setInstalling('')
    }
  }

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file || !selectedScope) return
    setUploading(true)
    try {
      await uploadSkillZip(file, selectedScope)
      await refreshScopeSkills(selectedScope)
      toast.success(`已上传 ${file.name}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '上传失败')
    } finally {
      setUploading(false)
      if (uploadRef.current) uploadRef.current.value = ''
    }
  }

  const handleGitScan = async () => {
    if (!gitUrl.trim()) return
    setGitScanning(true)
    setGitScan(null)
    setGitSelected(new Set())
    try {
      const result = await scanGitSkills(gitUrl.trim())
      setGitScan(result)
      setGitSelected(new Set(result.skills.map(skill => skill.name)))
    } catch (err) {
      showErrorMessage(gitErrorMessage(err))
    } finally {
      setGitScanning(false)
    }
  }

  const handleDeleteSkill = async (skill: SkillInfo) => {
    if (!selectedScope) return
    const targetScope = selectedScope
    const deletingSelected = selectedSkill?.scope === skill.scope && selectedSkill.name === skill.name
    try {
      await deleteSkill(skill)
      clearSkillsCache()
      if (deletingSelected) {
        filesRequestSeq.current += 1
        setSelectedSkill(null)
        setSkillFiles([])
        setFilesLoading(false)
      }
      if (editorFile?.skill.scope === skill.scope && editorFile.skill.name === skill.name) {
        setEditorFile(null)
      }
      const nextSkills = await refreshScopeSkills(targetScope)
      toast.success(`已删除 ${skill.name}`)
      if (deletingSelected) {
        const nextSkill = [...nextSkills].sort((a, b) => a.name.localeCompare(b.name))[0] || null
        if (!nextSkill) return
        selectSkill(nextSkill)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '删除失败')
    }
  }

  const openInstallModal = (modal: 'search' | 'git') => {
    if (!canInstallToSelectedScope) return
    setActiveModal(modal)
  }

  const handleEditFile = async (file: SkillFileInfo) => {
    if (!selectedSkill || !file.editable) return
    setEditorLoading(true)
    try {
      let result: { path: string; name: string; content: string }
      try {
        result = await getSkillFile(selectedSkill, file.path)
      } catch (err) {
        const legacyPath = legacySkillFilePath(selectedSkill, file.path)
        if (!legacyPath) throw err
        const legacy = await browseFiles(legacyPath) as BrowseFileResult
        if (legacy.type !== 'file' || legacy.content === undefined) throw err
        result = { path: file.path, name: legacy.name, content: legacy.content }
      }
      setEditorFile({
        skill: selectedSkill,
        path: result.path,
        name: result.name,
        content: result.content,
        originalContent: result.content,
      })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '读取文件失败')
    } finally {
      setEditorLoading(false)
    }
  }

  const handleSaveEditor = useCallback(async () => {
    if (!editorFile || editorSaving) return
    setEditorSaving(true)
    try {
      try {
        await writeSkillFile(editorFile.skill, editorFile.path, editorFile.content)
      } catch (err) {
        const legacyPath = legacySkillFilePath(editorFile.skill, editorFile.path)
        if (!legacyPath) throw err
        await writeManagedFile(legacyPath, editorFile.content)
      }
      setEditorFile(current => current ? { ...current, originalContent: current.content } : current)
      toast.success(`已保存 ${editorFile.name}`)
      await refreshSkillFiles(editorFile.skill)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '保存失败')
    } finally {
      setEditorSaving(false)
    }
  }, [editorFile, editorSaving, refreshSkillFiles])

  useEffect(() => {
    if (!editorFile) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void handleSaveEditor()
      }
      if (event.key === 'Escape') setEditorFile(null)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [editorFile, handleSaveEditor])

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-light-bg">
      <div className="flex min-h-0 flex-1 flex-col px-4 py-5 sm:px-5 lg:px-6">
        <header className="mb-4 flex shrink-0 flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <button
              type="button"
              onClick={openMobileSidebar}
              className="mb-3 inline-flex cursor-pointer items-center gap-2 rounded-xl border border-light-border bg-light-card px-3 py-2 text-sm text-light-text-secondary shadow-sm transition-colors hover:bg-light-card-hover hover:text-light-text lg:hidden"
            >
              <ArrowLeft size={16} />
              菜单
            </button>
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-purple/10 text-accent-purple">
                <Sparkles size={22} />
              </span>
              <div>
                <h1 className="text-2xl font-bold leading-tight tracking-normal text-light-text sm:text-[28px]">技能商店</h1>
                <p className="mt-1 text-sm text-light-text-secondary">查看各 Agent、全局和内置技能，并安装、导入、编辑技能文件</p>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <IconButton label="刷新技能" onClick={() => void refresh()} tone="primary" className="border border-light-border bg-light-card shadow-sm">
              <RefreshCw size={17} />
            </IconButton>
            <button
              type="button"
              onClick={() => openInstallModal('search')}
              disabled={!canInstallToSelectedScope}
              title={canInstallToSelectedScope ? '技能搜索' : '内置技能不支持安装'}
              className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-light-border bg-light-card px-4 py-2.5 text-sm font-medium text-light-text shadow-sm transition-colors hover:bg-light-card-hover disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Search size={17} />
              技能搜索
            </button>
            <button
              type="button"
              onClick={() => openInstallModal('git')}
              disabled={!canInstallToSelectedScope}
              title={canInstallToSelectedScope ? '从 Git 仓库导入' : '内置技能不支持导入'}
              className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-light-border bg-light-card px-4 py-2.5 text-sm font-medium text-light-text shadow-sm transition-colors hover:bg-light-card-hover disabled:cursor-not-allowed disabled:opacity-60"
            >
              <GitBranch size={17} />
              Git 导入
            </button>
            <label
              title={canInstallToSelectedScope ? '上传技能' : '内置技能不支持上传'}
              className={`inline-flex cursor-pointer items-center gap-2 rounded-xl bg-accent-blue px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-cyan-700 ${uploading || !canInstallToSelectedScope ? 'pointer-events-none opacity-60' : ''}`}
            >
              {uploading ? <Loader2 size={17} className="animate-spin" /> : <Upload size={17} />}
              上传技能
              <input ref={uploadRef} type="file" accept=".zip" className="hidden" onChange={handleUpload} disabled={!canInstallToSelectedScope} />
            </label>
          </div>
        </header>

        <div className={`grid min-h-0 flex-1 gap-4 overflow-hidden ${selectedSkill ? 'xl:grid-cols-[280px_minmax(0,1fr)_360px]' : 'xl:grid-cols-[280px_minmax(0,1fr)]'}`}>
          <aside className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-light-border bg-light-card p-3 shadow-sm shadow-slate-200/40">
            <div className="mb-3 flex shrink-0 items-center gap-2 text-sm font-semibold text-light-text">
              <Bot size={16} className="text-accent-blue" />
              安装位置
            </div>
            {loading ? (
              <SkillSkeleton />
            ) : (
              <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
                {sortedScopes.map(scope => (
                  <button
                    key={scope.id}
                    type="button"
                    onClick={() => selectScope(scope.id)}
                    className={`flex w-full cursor-pointer items-center justify-between gap-2 rounded-xl px-3 py-2 text-left text-sm transition-colors ${
                      scope.id === selectedScopeId
                        ? 'bg-accent-blue text-white shadow-sm'
                        : 'text-light-text-secondary hover:bg-light-card-hover hover:text-light-text'
                    }`}
                  >
                    <span className="min-w-0 flex-1 truncate">{scope.label}</span>
                    {!scope.writable && <span className="shrink-0 text-xs opacity-75">只读</span>}
                  </button>
                ))}
              </div>
            )}
          </aside>

          <main className="flex min-h-0 min-w-0 flex-col overflow-hidden">
            <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-light-border bg-light-card p-4 shadow-sm shadow-slate-200/40">
              <div className="mb-3 flex shrink-0 flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <h2 className="text-base font-semibold text-light-text">{selectedScope?.label || '技能'}</h2>
                  <p className="mt-0.5 text-xs text-light-text-secondary">{filteredSkills.length} 个技能</p>
                </div>
              </div>

              {loading ? (
                <SkillSkeleton />
              ) : filteredSkills.length === 0 ? (
                <div className="flex min-h-0 flex-1 items-center justify-center" aria-label="暂无技能">
                  <Inbox size={72} strokeWidth={1.5} className="text-light-text-secondary/45" aria-hidden="true" />
                </div>
              ) : (
                <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                  <div className="grid gap-3 md:grid-cols-2">
                    {filteredSkills.map(skill => (
                      <div
                        key={`${skill.scope}-${skill.name}`}
                        role="button"
                        tabIndex={0}
                        onClick={() => selectSkill(skill)}
                        onKeyDown={event => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault()
                            selectSkill(skill)
                          }
                        }}
                        className={`group relative cursor-pointer rounded-lg border p-4 pr-20 text-left transition-colors ${
                          selectedSkill?.scope === skill.scope && selectedSkill?.name === skill.name
                            ? 'border-accent-blue bg-accent-blue/5'
                            : 'border-light-border bg-light-card hover:border-accent-blue/40 hover:bg-light-card-hover/60'
                        }`}
                      >
                        <div className="absolute right-3 top-3 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                          <IconButton
                            label="下载技能"
                            onClick={event => {
                              event.stopPropagation()
                              void downloadSkill(skill)
                            }}
                            tone="primary"
                            surface="plain"
                            className="h-8 w-8 bg-light-card/90 shadow-sm"
                          >
                            <Download size={16} />
                          </IconButton>
                          {skill.writable && (
                            <Popconfirm
                              title="删除这个技能？"
                              description={`“${skill.name}”将从 ${skill.scopeLabel} 中删除，此操作不可恢复。`}
                              confirmText="删除"
                              danger
                              onConfirm={() => handleDeleteSkill(skill)}
                            >
                              <button type="button" className="inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg bg-light-card/90 text-light-text-secondary shadow-sm transition-colors hover:bg-accent-red/10 hover:text-accent-red" aria-label="删除技能">
                                <Trash2 size={16} />
                              </button>
                            </Popconfirm>
                          )}
                        </div>
                        <div className="flex items-start gap-3">
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-purple/10 text-accent-purple">
                            <Package size={18} />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-semibold text-light-text">{skill.name}</span>
                            <span className="mt-1 line-clamp-2 text-xs leading-5 text-light-text-secondary">{skill.description || '暂无描述'}</span>
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          </main>

          {selectedSkill && (
          <aside className="flex min-h-0 min-w-0 flex-col overflow-hidden">
            <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-light-border bg-light-card shadow-sm shadow-slate-200/40">
              <div className="border-b border-light-border px-4 py-3">
                <h2 className="text-base font-semibold text-light-text">{selectedSkill.name}</h2>
                <p className="mt-0.5 text-xs text-light-text-secondary">{selectedSkill.scopeLabel}</p>
              </div>
              {filesLoading ? (
                <SkillFileSkeleton />
              ) : (
                <div className="min-h-0 flex-1 overflow-y-auto">
                  {skillFiles.map(file => (
                    <button
                      key={file.path}
                      type="button"
                      onClick={() => void handleEditFile(file)}
                      disabled={!file.editable}
                      className="flex w-full cursor-pointer items-center gap-3 border-b border-light-border/70 px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-light-card-hover/70 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <FileText size={17} className="shrink-0 text-accent-blue" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-light-text">{file.path}</span>
                        <span className="block text-xs text-light-text-secondary">{formatSize(file.size)}</span>
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </section>
          </aside>
          )}
        </div>
      </div>

      {activeModal === 'search' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-3 py-4 sm:px-6 sm:py-6">
          <button type="button" className="absolute inset-0 cursor-default bg-slate-950/55 backdrop-blur-[2px]" aria-label="关闭技能搜索" onClick={() => setActiveModal(null)} />
          <section role="dialog" aria-modal="true" aria-label="技能搜索" className="relative flex h-[min(78vh,720px)] w-full max-w-[min(760px,calc(100vw-2rem))] flex-col overflow-hidden rounded-lg border border-light-border bg-light-card shadow-2xl shadow-slate-950/25">
            <header className="flex min-h-14 items-center justify-between gap-3 border-b border-light-border px-4 py-3">
              <div className="min-w-0">
                <h2 className="truncate text-base font-semibold text-light-text">技能搜索</h2>
                <p className="mt-0.5 truncate text-xs text-light-text-secondary">安装位置：{selectedScope?.label || '未选择'}</p>
              </div>
              <IconButton label="关闭技能搜索" onClick={() => setActiveModal(null)} className="border border-light-border">
                <X size={17} />
              </IconButton>
            </header>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4">
              {!canInstallToSelectedScope && (
                <div className="mb-3 shrink-0 rounded-lg border border-accent-yellow/25 bg-accent-yellow/10 px-3 py-2 text-sm text-amber-700">
                  当前是只读的内置技能位置，不支持安装。
                </div>
              )}
              <div className="flex shrink-0 flex-col gap-2 md:flex-row">
                <ClearableInput
                  value={query}
                  onValueChange={setQuery}
                  onKeyDown={event => {
                    if (event.key === 'Enter') void handleSearch()
                  }}
                  clearLabel="清空搜索"
                  placeholder="搜索 skills.sh"
                  className="min-w-0 flex-1 rounded-xl border border-light-border bg-light-card px-3 py-2 text-sm outline-none focus:border-accent-blue"
                />
                <button
                  type="button"
                  onClick={() => void handleSearch()}
                  disabled={!canInstallToSelectedScope || searching || !query.trim()}
                  className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl bg-accent-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {searching ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
                  搜索
                </button>
              </div>
              <div className="mt-4 min-h-0 flex-1 overflow-hidden rounded-lg border border-light-border">
                {searching ? (
                  <div className="flex h-full min-h-0 flex-col p-3">
                    <SkillSkeleton />
                  </div>
                ) : searchResults.length > 0 ? (
                  <div className="min-h-0 h-full divide-y divide-light-border/80 overflow-y-auto">
                    {searchResults.map(result => (
                      <div key={result.slug} className="flex items-center justify-between gap-3 px-3 py-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-light-text">{result.slug}</div>
                          <div className="text-xs text-light-text-secondary">
                            {result.installs}{result.sizeLabel ? ` · ${result.sizeLabel}` : ''}
                          </div>
                        </div>
                        <button
                          type="button"
                          disabled={!canInstallToSelectedScope || installing === result.slug}
                          onClick={() => void installWithRefresh(result.slug, () => installSkillFromSearch(result.slug, selectedScope!))}
                          className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-accent-blue/10 px-3 py-1.5 text-xs font-medium text-accent-blue transition-colors hover:bg-accent-blue/20 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {installing === result.slug ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                          安装
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="flex h-full min-h-0 items-center justify-center" aria-label="暂无搜索结果">
                    <Inbox size={64} strokeWidth={1.5} className="text-light-text-secondary/45" aria-hidden="true" />
                  </div>
                )}
              </div>
            </div>
          </section>
        </div>
      )}

      {activeModal === 'git' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-3 py-4 sm:px-6 sm:py-6">
          <button type="button" className="absolute inset-0 cursor-default bg-slate-950/55 backdrop-blur-[2px]" aria-label="关闭 Git 导入" onClick={() => setActiveModal(null)} />
          <section role="dialog" aria-modal="true" aria-label="从 Git 仓库导入" className="relative flex h-[min(78vh,720px)] w-full max-w-[min(760px,calc(100vw-2rem))] flex-col overflow-hidden rounded-lg border border-light-border bg-light-card shadow-2xl shadow-slate-950/25">
            <header className="flex min-h-14 items-center justify-between gap-3 border-b border-light-border px-4 py-3">
              <div className="min-w-0">
                <h2 className="truncate text-base font-semibold text-light-text">从 Git 仓库导入</h2>
                <p className="mt-0.5 truncate text-xs text-light-text-secondary">安装位置：{selectedScope?.label || '未选择'}</p>
              </div>
              <IconButton label="关闭 Git 导入" onClick={() => setActiveModal(null)} className="border border-light-border">
                <X size={17} />
              </IconButton>
            </header>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden p-4">
              {!canInstallToSelectedScope && (
                <div className="mb-3 shrink-0 rounded-lg border border-accent-yellow/25 bg-accent-yellow/10 px-3 py-2 text-sm text-amber-700">
                  当前是只读的内置技能位置，不支持导入。
                </div>
              )}
              <div className="flex shrink-0 flex-col gap-2 md:flex-row">
                <ClearableInput
                  value={gitUrl}
                  onValueChange={setGitUrl}
                  clearLabel="清空 Git 地址"
                  placeholder="https://github.com/user/repo.git"
                  className="min-w-0 flex-1 rounded-xl border border-light-border bg-light-card px-3 py-2 text-sm outline-none focus:border-accent-blue"
                />
                <button
                  type="button"
                  onClick={() => void handleGitScan()}
                  disabled={!canInstallToSelectedScope || gitScanning || !gitUrl.trim()}
                  className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-light-border px-4 py-2 text-sm font-medium text-light-text transition-colors hover:bg-light-card-hover disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {gitScanning ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
                  扫描
                </button>
              </div>
              <div className="mt-4 min-h-0 flex-1 overflow-hidden rounded-lg border border-light-border">
                {gitScanning ? (
                  <div className="flex h-full min-h-0 flex-col p-3">
                    <SkillSkeleton />
                  </div>
                ) : gitScan ? (
                  <div className="flex h-full min-h-0 flex-col">
                    <div className="flex shrink-0 flex-col gap-2 border-b border-light-border px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
                      <label className="inline-flex min-w-0 cursor-pointer items-center gap-3 text-light-text-secondary">
                        <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors ${
                          gitSelected.size === gitScan.skills.length && gitScan.skills.length > 0
                            ? 'border-accent-blue bg-accent-blue text-white'
                            : gitSelected.size > 0
                              ? 'border-accent-blue bg-accent-blue/10 text-accent-blue'
                              : 'border-light-border bg-light-card text-transparent'
                        }`}>
                          {gitSelected.size === gitScan.skills.length && gitScan.skills.length > 0 ? <Check size={12} /> : gitSelected.size > 0 ? <span className="h-0.5 w-2.5 rounded-full bg-current" /> : null}
                        </span>
                        <input
                          type="checkbox"
                          className="sr-only"
                          checked={gitSelected.size === gitScan.skills.length && gitScan.skills.length > 0}
                          disabled={gitInstalling || gitScan.skills.length === 0}
                          onChange={event => {
                            setGitSelected(event.target.checked ? new Set(gitScan.skills.map(skill => skill.name)) : new Set())
                          }}
                        />
                        <span className="truncate">发现 {gitScan.skills.length} 个技能</span>
                      </label>
                      <div className="flex flex-wrap items-center gap-2">
                        <button
                          type="button"
                          disabled={!canInstallToSelectedScope || gitInstalling || gitSelected.size === 0}
                          onClick={async () => {
                            if (!selectedScope || !gitScan) return
                            const targetScope = selectedScope
                            setGitInstalling(true)
                            try {
                              const result = await installGitSkills(gitScan.cacheKey, Array.from(gitSelected), targetScope)
                              if (result.errors.length > 0) showErrorMessage(`部分技能导入失败：${result.errors.join('；')}`)
                              await refreshScopeSkills(targetScope)
                              if (result.installed.length > 0) {
                                toast.success(`已安装 ${result.installed.length} 个技能到 ${targetScope.label}`)
                              }
                            } catch (err) {
                              showErrorMessage(err instanceof Error ? err.message : '导入失败，请稍后重试。')
                            } finally {
                              setGitInstalling(false)
                            }
                          }}
                          className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-accent-blue px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {gitInstalling ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                          安装选中
                        </button>
                      </div>
                    </div>
                    <div className="min-h-0 flex-1 overflow-y-auto">
                      {gitScan.skills.map(skill => (
                        <button
                          key={skill.name}
                          type="button"
                          onClick={() => setGitSelected(prev => {
                            const next = new Set(prev)
                            if (next.has(skill.name)) next.delete(skill.name)
                            else next.add(skill.name)
                            return next
                          })}
                          className="flex w-full cursor-pointer items-center gap-3 border-b border-light-border/70 px-3 py-2 text-left last:border-b-0 hover:bg-light-card-hover/70"
                        >
                          <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border ${gitSelected.has(skill.name) ? 'border-accent-blue bg-accent-blue text-white' : 'border-light-border'}`}>
                            {gitSelected.has(skill.name) && <Check size={12} />}
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate text-sm text-light-text">{skill.name}</span>
                            <span className="block truncate text-xs text-light-text-secondary">{skill.description || skill.relativePath}</span>
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="flex h-full min-h-0 items-center justify-center" aria-label="暂无 Git 扫描结果">
                    <Inbox size={64} strokeWidth={1.5} className="text-light-text-secondary/45" aria-hidden="true" />
                  </div>
                )}
              </div>
            </div>
          </section>
        </div>
      )}

      {(editorFile || editorLoading) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-3 py-4 sm:px-6 sm:py-6">
          <button type="button" className="absolute inset-0 cursor-default bg-slate-950/55 backdrop-blur-[2px]" aria-label="关闭技能编辑器" onClick={() => setEditorFile(null)} />
          <section role="dialog" aria-modal="true" aria-label="编辑技能文件" className="relative flex h-[min(88vh,900px)] w-full max-w-[min(1440px,calc(100vw-2rem))] flex-col overflow-hidden rounded-lg border border-light-border bg-light-card shadow-2xl shadow-slate-950/25">
            <header className="flex min-h-14 items-center justify-between gap-3 border-b border-light-border px-4 py-3">
              <div className="min-w-0">
                <h2 className="truncate text-base font-semibold text-light-text">{editorFile?.name || '正在读取文件'}</h2>
                <p className="mt-0.5 truncate text-xs text-light-text-secondary">{editorFile?.path || '请稍候'}</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {editorDirty && <span className="rounded-full bg-accent-yellow/10 px-2 py-1 text-xs font-medium text-amber-700">未保存</span>}
                <button type="button" disabled={!editorFile || editorSaving || !editorFile.skill.writable} onClick={() => void handleSaveEditor()} className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-accent-blue px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-60">
                  {editorSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                  保存
                </button>
                <IconButton label="关闭编辑器" onClick={() => setEditorFile(null)} className="border border-light-border">
                  <X size={17} />
                </IconButton>
              </div>
            </header>
            {editorLoading ? (
              <div className="flex flex-1 items-center justify-center gap-2 text-sm text-light-text-secondary">
                <Loader2 size={18} className="animate-spin text-accent-blue" />
                正在读取文件内容
              </div>
            ) : (
              <textarea
                value={editorFile?.content || ''}
                onChange={event => {
                  const value = event.target.value
                  setEditorFile(current => current ? { ...current, content: value } : current)
                }}
                spellCheck={false}
                autoFocus
                className="min-h-0 flex-1 resize-none border-0 bg-light-card px-4 py-4 font-mono text-sm leading-6 text-light-text outline-none"
              />
            )}
            <footer className="flex min-h-10 items-center justify-between gap-3 border-t border-light-border px-4 py-2 text-xs text-light-text-secondary">
              <span className="truncate">Ctrl+S 保存到技能目录</span>
            </footer>
          </section>
        </div>
      )}
    </div>
  )
}
