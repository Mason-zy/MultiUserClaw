import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { login, prewarmRuntime } from '../lib/api'

export default function LoginPassword() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      await login(username, password)
      void prewarmRuntime().catch(() => {})
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : '登录失败'
      setError(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-dark-bg">
      <div className="w-full max-w-md rounded-xl border border-dark-border bg-dark-card p-6">
        {/* Logo */}
        <div className="mb-6 flex flex-col items-center gap-2">
          <img
            src="/medclaw-logo.png"
            alt="MedClaw"
            className="h-10 w-10 rounded-lg"
          />
          <h1 className="text-lg font-semibold text-dark-text">MedClaw 医疗智能助手</h1>
          <p className="text-sm text-dark-muted">密码登录</p>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 rounded-lg bg-accent-red/10 p-3 text-sm text-accent-red">
            {error}
          </div>
        )}

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="mb-2 block text-sm font-medium text-dark-text">
              用户名
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-lg border border-dark-border bg-dark-bg px-4 py-2.5 text-dark-text placeholder-dark-muted focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
              placeholder="请输入用户名"
              disabled={loading}
              required
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-2 block text-sm font-medium text-dark-text">
              密码
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-dark-border bg-dark-bg px-4 py-2.5 text-dark-text placeholder-dark-muted focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
              placeholder="请输入密码"
              disabled={loading}
              required
            />
          </div>

          <button
            type="submit"
            disabled={loading || !username || !password}
            className="w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>登录中...</span>
              </>
            ) : (
              '登录'
            )}
          </button>
        </form>

        <p className="mt-4 text-center text-xs text-dark-muted">
          使用您的账号密码登录
        </p>
      </div>
    </div>
  )
}
