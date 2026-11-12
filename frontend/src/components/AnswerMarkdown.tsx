'use client'

import { memo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { cn } from '@/lib/utils'

interface Props {
  text: string
  validSources: Set<number>
  activeSource: number | null
  onCite: (n: number) => void
  streaming?: boolean
}

// Turn [3] markers into links the renderer can swap for citation chips.
// Skips [3](...) so real Markdown links are left alone.
const toCitationLinks = (text: string) => text.replace(/\[(\d{1,2})\](?!\()/g, '[$1](#cite-$1)')

function AnswerMarkdownImpl({ text, validSources, activeSource, onCite, streaming }: Props) {
  const components: Components = {
    a({ href, children }) {
      const cite = href?.match(/^#cite-(\d+)$/)
      if (cite) {
        const n = Number(cite[1])
        if (!validSources.has(n)) return <sup className="text-faint">[{n}]</sup>
        return (
          <button
            type="button"
            data-cite
            onClick={() => onCite(n)}
            aria-label={`Show source ${n}`}
            className={cn(
              'mx-0.5 inline-grid h-[1.15rem] min-w-[1.15rem] -translate-y-[0.35em] place-items-center rounded px-1',
              'align-baseline font-mono text-[0.68rem] font-semibold leading-none transition-colors',
              activeSource === n
                ? 'bg-accent text-paper'
                : 'bg-accent-soft text-accent hover:bg-accent hover:text-paper',
            )}
          >
            {n}
          </button>
        )
      }
      const safe = href && /^https?:\/\//.test(href) ? href : undefined
      return (
        <a href={safe} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      )
    },
  }

  return (
    <div className={cn('prose-answer', streaming && 'streaming-caret')}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {toCitationLinks(text)}
      </ReactMarkdown>
    </div>
  )
}

export const AnswerMarkdown = memo(AnswerMarkdownImpl)
