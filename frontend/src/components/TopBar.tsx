import { Settings, LogOut } from 'lucide-react'
import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { ping, logout, getContainerInfo } from '../lib/api'
import NotificationBell from './NotificationBell'
import ThemeToggle from './ThemeToggle'

type ServiceStatus = 'initializing' | 'online' | 'offline'

export default function TopBar() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<ServiceStatus>('initializing')
  const checkIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const checkServiceStatus = async (): Promise<boolean> => {
    try {
      // 先检查后端服务
      await ping()
      
      // 再检查容器状态
      const containerInfo = await getContainerInfo()
      const isContainerRunning = containerInfo.status === 'running'
      
      return isContainerRunning
    } catch {
      return false
    }
  }

  useEffect(() => {
    let initializeInterval: ReturnType<typeof setInterval> | null = null
    let hasStartedOnlineCheck = false

    const checkServiceStatusAndTransition = async () => {
      const isOnline = await checkServiceStatus()
      
      if (isOnline) {
        // 服务启动成功，切换到在线状态
        setStatus('online')
        
        // 清除初始化检查定时器
        if (initializeInterval) {
          clearInterval(initializeInterval)
          initializeInterval = null
        }
        
        // 清除超时定时器
        if (timeoutRef.current) {
          clearTimeout(timeoutRef.current)
          timeoutRef.current = null
        }
        
        // 启动定期检查（每30秒）
        if (!hasStartedOnlineCheck && !checkIntervalRef.current) {
          hasStartedOnlineCheck = true
          checkIntervalRef.current = setInterval(async () => {
            const stillOnline = await checkServiceStatus()
            setStatus(stillOnline ? 'online' : 'offline')
          }, 30000)
        }
      }
    }

    // 立即开始第一次检查
    checkServiceStatusAndTransition()

    // 在初始化阶段每2秒检查一次
    initializeInterval = setInterval(() => {
      checkServiceStatusAndTransition()
    }, 2000)

    // 设置30秒超时
    timeoutRef.current = setTimeout(async () => {
      // 如果30秒后仍未在线，则切换到离线状态
      const isOnline = await checkServiceStatus()
      if (!isOnline) {
        setStatus('offline')
      }
      
      // 清除初始化检查定时器
      if (initializeInterval) {
        clearInterval(initializeInterval)
        initializeInterval = null
      }
    }, 30000)

    return () => {
      if (initializeInterval) {
        clearInterval(initializeInterval)
      }
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current)
        checkIntervalRef.current = null
      }
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
        timeoutRef.current = null
      }
    }
  }, [])

  const getStatusConfig = () => {
    switch (status) {
      case 'initializing':
        return {
          borderColor: 'border-yellow-500/30',
          textColor: 'text-yellow-500',
          dotColor: 'bg-yellow-500',
          text: '服务初始化中',
        }
      case 'online':
        return {
          borderColor: 'border-accent-green/30',
          textColor: 'text-accent-green',
          dotColor: 'bg-accent-green',
          text: '服务运行中',
        }
      case 'offline':
        return {
          borderColor: 'border-accent-red/30',
          textColor: 'text-accent-red',
          dotColor: 'bg-accent-red',
          text: '服务离线',
        }
    }
  }

  const statusConfig = getStatusConfig()

  return (
    <header className="flex h-14 items-center justify-between border-b border-dark-border bg-dark-sidebar px-6">
      <div />

      {/* Right side */}
      <div className="flex items-center gap-4">
        <div
          className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium border ${statusConfig.borderColor} ${statusConfig.textColor}`}
        >
          <span
            className={`h-2 w-2 rounded-full ${statusConfig.dotColor} ${
              status === 'initializing' ? 'animate-pulse' : ''
            }`}
          />
          {statusConfig.text}
        </div>

        {/* 主题切换 */}
        <ThemeToggle />

        {/* ✅ 使用组件 */}
        <NotificationBell />

        {/* 设置 */}
        <button
          onClick={() => navigate('/settings')}
          className="text-dark-text-secondary hover:text-dark-text transition-colors"
          title="系统设置"
        >
          <Settings size={20} />
        </button>

        {/* 退出 */}
        <button
          onClick={() => logout()}
          className="text-dark-text-secondary hover:text-accent-red transition-colors"
          title="退出登录"
        >
          <LogOut size={20} />
        </button>
      </div>
    </header>
  )
}