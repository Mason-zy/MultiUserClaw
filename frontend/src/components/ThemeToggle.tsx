import { Sun, Moon } from 'lucide-react'
import { useState, useEffect } from 'react'

export default function ThemeToggle() {
  const [isLight, setIsLight] = useState(() => {
    return localStorage.getItem('theme') === 'light'
  })

  useEffect(() => {
    if (isLight) {
      document.documentElement.classList.add('light')
      localStorage.setItem('theme', 'light')
    } else {
      document.documentElement.classList.remove('light')
      localStorage.setItem('theme', 'dark')
    }
  }, [isLight])

  return (
    <button
      onClick={() => setIsLight(!isLight)}
      className="text-dark-text-secondary hover:text-dark-text transition-colors"
      title={isLight ? '切换暗色主题' : '切换亮色主题'}
    >
      {isLight ? <Moon size={20} /> : <Sun size={20} />}
    </button>
  )
}
