import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { memo, useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { fileDownloadLinkRenderer, remarkFileLinks } from './FileDownloadPlugin'

function CodeBlock({ className, children }: { className?: string; children: React.ReactNode }) {
  const [copied, setCopied] = useState(false)
  const match = /language-(\w+)/.exec(className || '')
  const lang = match?.[1] || ''
  const code = String(children).replace(/\n$/, '')

  const handleCopy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="group relative my-2 rounded-lg bg-dark-card border border-dark-border overflow-hidden">
      <div className="flex items-center justify-between px-3 py-1.5 bg-dark-bg/50 border-b border-dark-border">
        <span className="text-[10px] text-dark-text-secondary uppercase tracking-wider">{lang || 'code'}</span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 text-[10px] text-dark-text-secondary hover:text-dark-text transition-colors"
        >
          {copied ? <><Check size={11} /> 已复制</> : <><Copy size={11} /> 复制</>}
        </button>
      </div>
      <pre className="overflow-x-auto p-3 text-xs leading-relaxed">
        <code className={className}>{code}</code>
      </pre>
    </div>
  )
}

export default memo(function MarkdownContent({ content, className = '' }: { content: string; className?: string }) {
  return (
    <div className={`markdown-body text-sm leading-relaxed ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkFileLinks]}
        components={{
          // Code blocks
          code({ className, children, ...props }) {
            const isBlock = /language-/.test(className || '') ||
              (typeof children === 'string' && children.includes('\n'))
            if (isBlock) {
              return <CodeBlock className={className}>{children}</CodeBlock>
            }
            return (
              <code
                className="rounded bg-dark-bg/80 px-1.5 py-0.5 text-xs text-accent-blue font-mono"
                {...props}
              >
                {children}
              </code>
            )
          },
          // Block-level pre: just pass through children (CodeBlock handles wrapping)
          pre({ children }) {
            return <>{children}</>
          },
          // Paragraphs
          p({ children }) {
            return <p className="mb-2 last:mb-0">{children}</p>
          },
          // Headings
          h1({ children }) { return <h1 className="text-lg font-bold mb-2 mt-3">{children}</h1> },
          h2({ children }) { return <h2 className="text-base font-bold mb-2 mt-3">{children}</h2> },
          h3({ children }) { return <h3 className="text-sm font-bold mb-1.5 mt-2">{children}</h3> },
          // Lists
          ul({ children }) { return <ul className="mb-2 ml-4 list-disc space-y-0.5 last:mb-0">{children}</ul> },
          ol({ children }) { return <ol className="mb-2 ml-4 list-decimal space-y-0.5 last:mb-0">{children}</ol> },
          li({ children }) { return <li className="text-sm">{children}</li> },
          // Blockquote
          blockquote({ children }) {
            return (
              <blockquote className="my-2 border-l-2 border-accent-blue/40 pl-3 text-dark-text-secondary italic">
                {children}
              </blockquote>
            )
          },
          // Table
          table({ children }) {
            return (
              <div className="my-2 overflow-x-auto rounded-lg border border-dark-border">
                <table className="w-full text-xs">{children}</table>
              </div>
            )
          },
          thead({ children }) { return <thead className="bg-dark-bg/50">{children}</thead> },
          th({ children }) { return <th className="px-3 py-1.5 text-left font-medium text-dark-text-secondary border-b border-dark-border">{children}</th> },
          td({ children }) { return <td className="px-3 py-1.5 border-b border-dark-border/50">{children}</td> },
          // Links (工作区文件路径自动渲染为下载卡片)
          a: fileDownloadLinkRenderer,
          // Images: hide inline markdown images (files are shown as download cards below)
          img() { return null },
          // Horizontal rule
          hr() { return <hr className="my-3 border-dark-border" /> },
          // Strong / Em
          strong({ children }) { return <strong className="font-semibold">{children}</strong> },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
})
