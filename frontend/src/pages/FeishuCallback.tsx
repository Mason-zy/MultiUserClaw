import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { setTokens } from '../lib/api'

/**
 * Feishu OAuth landing page.
 *
 * The backend (/api/auth/feishu/callback) 302-redirects here with the platform
 * JWTs in the query string: access_token & refresh_token on success, or
 * `error` on failure. We persist the tokens using the same convention as the
 * username/password login (api.setTokens) then route to the dashboard.
 */
export default function FeishuCallback() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [message, setMessage] = useState('正在完成飞书登录…')

  useEffect(() => {
    const accessToken = params.get('access_token')
    const refreshToken = params.get('refresh_token')
    const error = params.get('error')

    if (error) {
      setMessage(`飞书登录失败：${error}`)
      return
    }

    if (accessToken && refreshToken) {
      setTokens(accessToken, refreshToken)
      navigate('/', { replace: true })
      return
    }

    // Neither token nor error — treat as invalid direct access.
    navigate('/login', { replace: true })
  }, [params, navigate])

  return (
    <div className="flex min-h-screen items-center justify-center bg-dark-bg">
      <div className="flex flex-col items-center gap-3 text-dark-muted">
        <Loader2 className="h-6 w-6 animate-spin" />
        <p className="text-sm">{message}</p>
        {message.startsWith('飞书登录失败') && (
          <button
            type="button"
            onClick={() => navigate('/login', { replace: true })}
            className="mt-2 text-sm text-accent-blue hover:underline"
          >
            返回登录
          </button>
        )}
      </div>
    </div>
  )
}
