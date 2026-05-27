import { useState, useEffect, useRef } from 'react'
import { listSkills, searchSkills, installSkill, toggleSkill, deleteSkill, scanGitSkills, installGitSkills, uploadSkillZip, downloadSkillUrl, getAccessToken, getRecommendedSkills, installRecommendedSkill } from '../lib/api'
import type { Skill, SkillSearchResult, GitScanResult, RecommendedCategory } from '../lib/api'
import { Zap, Loader2, Search, Download, ExternalLink, Check, GitBranch, Upload, Trash2, ChevronLeft, ChevronRight, Tag } from 'lucide-react'

export default function SkillStore() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)

  // Search state
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [results, setResults] = useState<SkillSearchResult[]>([])
  const [searched, setSearched] = useState(false)

  // Install state
  const [installing, setInstalling] = useState<string | null>(null)
  const [installed, setInstalled] = useState<Set<string>>(new Set())
  const [installError, setInstallError] = useState('')

  // Toggle state
  const [toggling, setToggling] = useState<string | null>(null)

  // Delete state
  const [deleting, setDeleting] = useState<string | null>(null)

  // Upload state
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState('')

  // Recommended skills state
  const [recCategories, setRecCategories] = useState<RecommendedCategory[]>([])
  const [recLoading, setRecLoading] = useState(true)
  const [recActiveTab, setRecActiveTab] = useState<string | null>(null)
  const [recInstalling, setRecInstalling] = useState<string | null>(null)
  const [recInstalled, setRecInstalled] = useState<Set<string>>(new Set())
  const scrollRef = useRef<HTMLDivElement>(null)

  // Git repo state
  const [gitUrl, setGitUrl] = useState('')
  const [gitScanning, setGitScanning] = useState(false)
  const [gitScanResult, setGitScanResult] = useState<GitScanResult | null>(null)
  const [gitSelected, setGitSelected] = useState<Set<string>>(new Set())
  const [gitInstalling, setGitInstalling] = useState(false)
  const [gitError, setGitError] = useState('')
  const [gitInstalled, setGitInstalled] = useState<Set<string>>(new Set())

  const refreshSkills = () => {
    listSkills().then(setSkills).catch(() => setSkills([]))
  }

  useEffect(() => {
    listSkills()
      .then(setSkills)
      .catch(() => setSkills([]))
      .finally(() => setLoading(false))

    getRecommendedSkills()
      .then(data => {
        setRecCategories(data.categories || [])
        if (data.categories?.length > 0) {
          setRecActiveTab(data.categories[0].id)
        }
      })
      .catch(() => setRecCategories([]))
      .finally(() => setRecLoading(false))
  }, [])

  const handleRecInstall = async (category: string, skillName: string) => {
    if (recInstalling) return
    setRecInstalling(skillName)
    setInstallError('')
    try {
      await installRecommendedSkill(category, skillName)
      setRecInstalled(prev => new Set(prev).add(skillName))
      refreshSkills()
    } catch (err: any) {
      setInstallError(err?.message || '安装失败')
    } finally {
      setRecInstalling(null)
    }
  }

  const scrollCategory = (dir: 'left' | 'right') => {
    if (!scrollRef.current) return
    const amount = 300
    scrollRef.current.scrollBy({ left: dir === 'left' ? -amount : amount, behavior: 'smooth' })
  }

  const handleSearch = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!query.trim() || searching) return
    setSearching(true)
    setSearched(true)
    setInstallError('')
    try {
      const data = await searchSkills(query.trim(), 10)
      setResults(data.results || [])
    } catch {
      setResults([])
    } finally {
      setSearching(false)
    }
  }

  const handleInstall = async (slug: string) => {
    if (installing) return
    setInstalling(slug)
    setInstallError('')
    try {
      await installSkill(slug)
      setInstalled(prev => new Set(prev).add(slug))
      refreshSkills()
    } catch (err: any) {
      setInstallError(err?.message || '安装失败')
    } finally {
      setInstalling(null)
    }
  }

  const handleToggle = async (skill: Skill) => {
    if (toggling) return
    const newEnabled = skill.disabled !== false // if disabled or undefined, enable it
    setToggling(skill.name)
    try {
      await toggleSkill(skill.name, newEnabled)
      // Update local state immediately
      setSkills(prev =>
        prev.map(s =>
          s.name === skill.name ? { ...s, disabled: !newEnabled } : s
        )
      )
    } catch {
      // Revert on error — refresh from server
      refreshSkills()
    } finally {
      setToggling(null)
    }
  }

  const handleDelete = async (skill: Skill) => {
    if (deleting) return
    if (!window.confirm(`确定要删除技能「${skill.name}」吗？`)) return
    setDeleting(skill.name)
    setInstallError('')
    try {
      await deleteSkill(skill.path || skill.name)
      setSkills(prev => prev.filter(s => s.name !== skill.name))
    } catch (err: any) {
      setInstallError(err?.message || `删除技能「${skill.name}」失败`)
    } finally {
      setDeleting(null)
    }
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = '' // reset input
    setUploading(true)
    setUploadMsg('')
    setInstallError('')
    try {
      const result = await uploadSkillZip(file)
      const installedCount = result.installed?.length || 1
      setUploadMsg(
        installedCount > 1
          ? `已上传 ${installedCount} 个技能，首个为「${result.name}」`
          : `技能「${result.name}」上传成功`
      )
      refreshSkills()
      setTimeout(() => setUploadMsg(''), 3000)
    } catch (err: any) {
      setInstallError(err?.message || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const handleDownload = async (name: string) => {
    const url = downloadSkillUrl(name)
    const token = getAccessToken()
    try {
      const res = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) throw new Error('Download failed')
      const blob = await res.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      const filename = name.includes('/') ? name.split('/').pop()! : name
      a.download = `${filename}.zip`
      a.click()
      URL.revokeObjectURL(a.href)
    } catch {
      setInstallError(`下载技能「${name}」失败`)
    }
  }

  const handleGitScan = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!gitUrl.trim() || gitScanning) return
    setGitScanning(true)
    setGitError('')
    setGitScanResult(null)
    setGitSelected(new Set())
    setGitInstalled(new Set())
    try {
      const result = await scanGitSkills(gitUrl.trim())
      setGitScanResult(result)
      // Auto-select all skills
      setGitSelected(new Set(result.skills.map(s => s.name)))
    } catch (err: any) {
      setGitError(err?.message || '克隆仓库失败')
    } finally {
      setGitScanning(false)
    }
  }

  const toggleGitSkillSelect = (name: string) => {
    setGitSelected(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const handleGitInstall = async () => {
    if (!gitScanResult || gitSelected.size === 0 || gitInstalling) return
    setGitInstalling(true)
    setGitError('')
    try {
      const result = await installGitSkills(gitScanResult.cacheKey, Array.from(gitSelected))
      if (result.installed.length > 0) {
        setGitInstalled(new Set(result.installed))
        refreshSkills()
      }
      if (result.errors.length > 0) {
        setGitError(result.errors.join('; '))
      }
    } catch (err: any) {
      setGitError(err?.message || '安装失败')
    } finally {
      setGitInstalling(false)
    }
  }

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-dark-text">技能商店</h1>
          <p className="mt-1 text-sm text-dark-text-secondary">
            搜索并安装来自 <a href="https://skills.sh/" target="_blank" rel="noreferrer" className="text-accent-blue hover:underline">skills.sh</a> 的 AI 技能扩展
          </p>
        </div>
        <label className={`flex items-center gap-2 rounded-lg border border-dark-border px-4 py-2 text-sm text-dark-text-secondary hover:text-dark-text hover:border-accent-blue transition-colors cursor-pointer ${uploading ? 'opacity-50 pointer-events-none' : ''}`}>
          {uploading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
          {uploading ? '上传中...' : '上传技能 (.zip)'}
          <input type="file" accept=".zip" onChange={handleUpload} className="hidden" disabled={uploading} />
        </label>
      </div>

      {uploadMsg && (
        <div className="mb-4 rounded-lg bg-accent-green/10 p-3 text-sm text-accent-green flex items-center gap-2">
          <Check size={16} />
          {uploadMsg}
        </div>
      )}

      {/* Search bar */}
      <form onSubmit={handleSearch} className="mb-6 flex gap-3">
        <div className="flex flex-1 items-center gap-2 rounded-lg border border-dark-border bg-dark-card px-4 py-2.5">
          <Search size={16} className="text-dark-text-secondary" />
          <input
            type="text"
            placeholder="搜索技能，例如：web scraping, react, testing..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            className="flex-1 bg-transparent text-sm text-dark-text outline-none placeholder:text-dark-text-secondary"
          />
        </div>
        <button
          type="submit"
          disabled={searching || !query.trim()}
          className="flex items-center gap-2 rounded-lg bg-accent-blue px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-blue/90 disabled:opacity-50 transition-colors"
        >
          {searching ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
          搜索
        </button>
      </form>

      {/* Recommended skills by category */}
      {recLoading ? (
        <div className="mb-6 flex items-center justify-center py-8">
          <Loader2 size={20} className="animate-spin text-accent-blue" />
          <span className="ml-2 text-sm text-dark-text-secondary">加载推荐技能...</span>
        </div>
      ) : recCategories.length > 0 && (
        <div className="mb-6">
          <h2 className="mb-3 text-base font-semibold text-dark-text flex items-center gap-2">
            <Tag size={16} className="text-accent-purple" />
            推荐技能
          </h2>

          {/* Category tabs with horizontal scroll */}
          <div className="relative mb-4">
            <button
              onClick={() => scrollCategory('left')}
              className="absolute left-0 top-0 z-10 flex h-full items-center bg-gradient-to-r from-dark-bg to-transparent pl-1 pr-3"
            >
              <ChevronLeft size={16} className="text-dark-text-secondary hover:text-dark-text" />
            </button>
            <div ref={scrollRef} className="flex gap-2 overflow-x-auto scrollbar-hide px-6">
              {recCategories.map(cat => (
                <button
                  key={cat.id}
                  onClick={() => setRecActiveTab(cat.id)}
                  className={`flex shrink-0 items-center gap-1.5 rounded-full px-4 py-1.5 text-sm transition-colors ${
                    recActiveTab === cat.id
                      ? 'bg-accent-blue text-white'
                      : 'bg-dark-card border border-dark-border text-dark-text-secondary hover:text-dark-text hover:border-accent-blue/30'
                  }`}
                >
                  <span>{cat.icon}</span>
                  <span>{cat.name}</span>
                  <span className="text-xs opacity-70">({cat.skills.length})</span>
                </button>
              ))}
            </div>
            <button
              onClick={() => scrollCategory('right')}
              className="absolute right-0 top-0 z-10 flex h-full items-center bg-gradient-to-l from-dark-bg to-transparent pr-1 pl-3"
            >
              <ChevronRight size={16} className="text-dark-text-secondary hover:text-dark-text" />
            </button>
          </div>

          {/* Active category description */}
          {recCategories.filter(c => c.id === recActiveTab).map(cat => (
            <p key={cat.id} className="mb-3 text-xs text-dark-text-secondary">{cat.description}</p>
          ))}

          {/* Skills grid for active category */}
          {recCategories.filter(c => c.id === recActiveTab).map(cat => (
            <div key={cat.id} className="grid grid-cols-3 gap-3">
              {cat.skills.map(skill => {
                const isAlreadyInstalled = skills.some(s => s.name === skill.name)
                const justInstalled = recInstalled.has(skill.name)
                const isDone = isAlreadyInstalled || justInstalled
                const isInstalling = recInstalling === skill.name
                return (
                  <div
                    key={skill.name}
                    className={`rounded-xl border p-4 transition-colors ${
                      isDone
                        ? 'border-accent-green/30 bg-accent-green/5'
                        : 'border-dark-border bg-dark-card hover:border-accent-blue/30'
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <h3 className="text-sm font-semibold text-dark-text truncate flex-1">{skill.name}</h3>
                      <button
                        onClick={() => handleRecInstall(skill.category, skill.name)}
                        disabled={isDone || isInstalling}
                        className={`ml-2 flex shrink-0 items-center gap-1 rounded-lg px-3 py-1 text-xs font-medium transition-colors ${
                          isDone
                            ? 'bg-accent-green/10 text-accent-green'
                            : 'bg-accent-blue/10 text-accent-blue hover:bg-accent-blue/20 disabled:opacity-50'
                        }`}
                      >
                        {isInstalling ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : isDone ? (
                          <><Check size={12} /> 已安装</>
                        ) : (
                          <><Download size={12} /> 安装</>
                        )}
                      </button>
                    </div>
                    <p className="mt-1.5 text-xs text-dark-text-secondary leading-relaxed line-clamp-2">{skill.description}</p>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}

      {/* Git repo import */}
      <div className="mb-6 rounded-xl border border-dark-border bg-dark-card p-5">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-dark-text">
          <GitBranch size={16} className="text-accent-purple" />
          从 Git 仓库导入技能
        </h2>
        <form onSubmit={handleGitScan} className="flex gap-3">
          <div className="flex flex-1 items-center gap-2 rounded-lg border border-dark-border bg-dark-bg px-4 py-2.5">
            <GitBranch size={14} className="text-dark-text-secondary" />
            <input
              type="text"
              placeholder="输入 Git 仓库地址，如 https://github.com/user/repo.git 或 git@github.com:user/repo.git"
              value={gitUrl}
              onChange={e => setGitUrl(e.target.value)}
              className="flex-1 bg-transparent text-sm text-dark-text outline-none placeholder:text-dark-text-secondary"
            />
          </div>
          <button
            type="submit"
            disabled={gitScanning || !gitUrl.trim()}
            className="flex items-center gap-2 rounded-lg bg-accent-purple px-5 py-2.5 text-sm font-medium text-white hover:bg-accent-purple/90 disabled:opacity-50 transition-colors"
          >
            {gitScanning ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
            扫描
          </button>
        </form>

        {gitError && (
          <div className="mt-3 rounded-lg bg-accent-red/10 p-3 text-sm text-accent-red">
            {gitError}
          </div>
        )}

        {gitScanResult && (
          <div className="mt-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm text-dark-text-secondary">
                仓库 <span className="font-medium text-dark-text">{gitScanResult.repoName}</span> 中发现 {gitScanResult.skills.length} 个技能
              </span>
              {gitScanResult.skills.length > 0 && (
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => {
                      if (gitSelected.size === gitScanResult.skills.length) {
                        setGitSelected(new Set())
                      } else {
                        setGitSelected(new Set(gitScanResult.skills.map(s => s.name)))
                      }
                    }}
                    className="text-xs text-accent-blue hover:underline"
                  >
                    {gitSelected.size === gitScanResult.skills.length ? '取消全选' : '全选'}
                  </button>
                  <button
                    onClick={handleGitInstall}
                    disabled={gitInstalling || gitSelected.size === 0}
                    className="flex items-center gap-1.5 rounded-lg bg-accent-green px-4 py-1.5 text-xs font-medium text-white hover:bg-accent-green/90 disabled:opacity-50 transition-colors"
                  >
                    {gitInstalling ? (
                      <><Loader2 size={13} className="animate-spin" /> 安装中...</>
                    ) : (
                      <><Download size={13} /> 安装选中 ({gitSelected.size})</>
                    )}
                  </button>
                </div>
              )}
            </div>

            {gitScanResult.skills.length === 0 ? (
              <div className="rounded-lg border border-dark-border bg-dark-bg p-4 text-center text-sm text-dark-text-secondary">
                该仓库中未找到技能（需要包含 SKILL.md 文件的目录）
              </div>
            ) : (
              <div className="space-y-1.5">
                {gitScanResult.skills.map(skill => {
                  const isSelected = gitSelected.has(skill.name)
                  const isDone = gitInstalled.has(skill.name)
                  return (
                    <div
                      key={skill.name}
                      onClick={() => !isDone && toggleGitSkillSelect(skill.name)}
                      className={`flex cursor-pointer items-center gap-3 rounded-lg border px-4 py-3 transition-colors ${
                        isDone
                          ? 'border-accent-green/30 bg-accent-green/5'
                          : isSelected
                            ? 'border-accent-purple/40 bg-accent-purple/5'
                            : 'border-dark-border bg-dark-bg hover:border-dark-border/80'
                      }`}
                    >
                      <div className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors ${
                        isDone
                          ? 'border-accent-green bg-accent-green text-white'
                          : isSelected
                            ? 'border-accent-purple bg-accent-purple text-white'
                            : 'border-dark-border'
                      }`}>
                        {(isSelected || isDone) && <Check size={12} />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-dark-text">{skill.name}</span>
                          <span className="text-xs text-dark-text-secondary">{skill.relativePath}</span>
                        </div>
                        {skill.description && (
                          <p className="mt-0.5 text-xs text-dark-text-secondary truncate">{skill.description}</p>
                        )}
                      </div>
                      {isDone && (
                        <span className="shrink-0 text-xs font-medium text-accent-green">已安装</span>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {installError && (
        <div className="mb-4 rounded-lg bg-accent-red/10 p-3 text-sm text-accent-red">
          {installError}
        </div>
      )}

      {/* Search results */}
      {searched && (
        <div className="mb-8">
          <h2 className="mb-3 text-base font-semibold text-dark-text">
            搜索结果
            {results.length > 0 && <span className="ml-2 text-sm font-normal text-dark-text-secondary">({results.length} 个技能)</span>}
          </h2>
          {searching ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={24} className="animate-spin text-accent-blue" />
              <span className="ml-3 text-sm text-dark-text-secondary">正在搜索...</span>
            </div>
          ) : results.length === 0 ? (
            <div className="rounded-xl border border-dark-border bg-dark-card p-8 text-center text-sm text-dark-text-secondary">
              未找到相关技能，请尝试其他关键词
            </div>
          ) : (
            <div className="space-y-2">
              {results.map(r => {
                const isInstalled = installed.has(r.slug)
                const isInstalling = installing === r.slug
                return (
                  <div key={r.slug} className="flex items-center justify-between rounded-xl border border-dark-border bg-dark-card px-5 py-3.5 hover:border-accent-blue/30 transition-colors">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-dark-text truncate">{r.slug}</span>
                        <span className="shrink-0 rounded bg-dark-bg px-2 py-0.5 text-xs text-dark-text-secondary">{r.installs}</span>
                      </div>
                      <a
                        href={r.url}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1 flex items-center gap-1 text-xs text-accent-blue/70 hover:text-accent-blue truncate"
                      >
                        <ExternalLink size={11} />
                        {r.url}
                      </a>
                    </div>
                    <button
                      onClick={() => handleInstall(r.slug)}
                      disabled={isInstalling || isInstalled}
                      className={`ml-4 flex shrink-0 items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-medium transition-colors ${
                        isInstalled
                          ? 'bg-accent-green/10 text-accent-green'
                          : 'bg-accent-blue/10 text-accent-blue hover:bg-accent-blue/20 disabled:opacity-50'
                      }`}
                    >
                      {isInstalling ? (
                        <><Loader2 size={13} className="animate-spin" /> 安装中...</>
                      ) : isInstalled ? (
                        <><Check size={13} /> 已安装</>
                      ) : (
                        <><Download size={13} /> 安装</>
                      )}
                    </button>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Installed skills */}
      <div>
        <h2 className="mb-3 text-base font-semibold text-dark-text">
          已安装技能
          {skills.length > 0 && <span className="ml-2 text-sm font-normal text-dark-text-secondary">({skills.length})</span>}
        </h2>
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 size={24} className="animate-spin text-accent-blue" />
          </div>
        ) : skills.length === 0 ? (
          <div className="rounded-xl border border-dark-border bg-dark-card p-8 text-center text-sm text-dark-text-secondary">
            暂无已安装技能，使用上方搜索栏查找并安装
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-4">
            {skills.map(skill => {
              const isDisabled = skill.disabled === true
              const isToggling = toggling === skill.name
              return (
                <div
                  key={skill.name}
                  className={`rounded-xl border bg-dark-card p-5 transition-colors ${
                    isDisabled
                      ? 'border-dark-border/50 opacity-60'
                      : 'border-dark-border hover:border-accent-blue/30'
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent-yellow/10">
                      <Zap size={20} className={isDisabled ? 'text-dark-text-secondary' : 'text-accent-yellow'} />
                    </div>
                    {/* Toggle switch */}
                    <button
                      onClick={() => handleToggle(skill)}
                      disabled={isToggling}
                      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
                        isDisabled ? 'bg-dark-border' : 'bg-accent-green'
                      } ${isToggling ? 'opacity-50' : 'cursor-pointer'}`}
                      title={isDisabled ? '点击启用' : '点击禁用'}
                    >
                      <span
                        className={`inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform ${
                          isDisabled ? 'translate-x-0.5' : 'translate-x-[18px]'
                        }`}
                      />
                    </button>
                  </div>
                  <h3 className="mt-3 text-sm font-semibold text-dark-text">{skill.name}</h3>
                  <p className="mt-1 text-xs text-dark-text-secondary leading-relaxed line-clamp-2">{skill.description}</p>
                  <div className="mt-3 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {skill.source && (
                        <span className="text-xs text-dark-text-secondary">
                          来源: {skill.source}
                        </span>
                      )}
                      {isDisabled && (
                        <span className="text-xs text-accent-yellow">已禁用</span>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDownload(skill.path || skill.name) }}
                        className="flex items-center gap-1 rounded px-2 py-1 text-xs text-dark-text-secondary hover:text-accent-blue hover:bg-accent-blue/10 transition-colors"
                        title={`下载 ${skill.name}.zip`}
                      >
                        <Download size={12} />
                        下载
                      </button>
                      {skill.source !== 'builtin' && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDelete(skill) }}
                          disabled={deleting === skill.name}
                          className="flex items-center gap-1 rounded px-2 py-1 text-xs text-dark-text-secondary hover:text-accent-red hover:bg-accent-red/10 transition-colors disabled:opacity-50"
                          title={`删除 ${skill.name}`}
                        >
                          {deleting === skill.name ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                          删除
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
