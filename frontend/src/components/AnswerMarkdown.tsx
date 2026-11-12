'use client'

import { memo, useMemo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import remarkCitations from '@/lib/remarkCitations'
import { cn } from '@/lib/utils'

interface Props {
  text: string
  validSources: Set<number>
  activeSource: number | null
  onCite: (n: number) => void
  streaming?: boolean
}

const PLUGINS = [remarkGfm, remarkCitations]
// Answers are model output built from uploaded documents. Never render images (a remote
// <img> can leak data to a URL a malicious document asked for) or raw HTML.
const DISALLOWED = ['img']

function AnswerMarkdownImpl({ text, validSources, activeSource, onCite, streaming }: Props) {
  const components = useMemo<Components>(
    () => ({
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
              aria-label={`Source ${n}`}
              aria-pressed={activeSource === n}
              className={cn(
                // 20px chip with a 24px invisible hit area (WCAG 2.5.8).
                'relative mx-0.5 inline-grid h-5 min-w-5 -translate-y-[0.3em] place-items-center rounded px-1',
                "after:absolute after:-inset-0.5 after:content-['']",
                'align-baseline font-mono text-[0.7rem] leading-none font-semibold transition-colors',
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
    }),
    [validSources, activeSource, onCite],
  )

  return (
    <div className={cn('prose-answer', streaming && 'streaming-caret')}>
      <ReactMarkdown remarkPlugins={PLUGINS} components={components} disallowedElements={DISALLOWED}>
        {text}
      </ReactMarkdown>
    </div>
  )
}

export const AnswerMarkdown = memo(AnswerMarkdownImpl)
