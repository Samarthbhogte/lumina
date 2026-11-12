'use client'

import { BookOpen } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { SourceCard } from './SourceCard'
import type { AssistantMessage } from './types'

interface Props {
  message: AssistantMessage | null
  activeSource: number | null
  onSelect: (n: number) => void
}

export function SourcesPanel({ message, activeSource, onSelect }: Props) {
  const refs = useRef(new Map<number, HTMLLIElement>())

  useEffect(() => {
    if (activeSource !== null) refs.current.get(activeSource)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [activeSource, message?.id])

  const cited = new Set(message?.result?.cited ?? [])
  const sources = [...(message?.sources ?? [])].sort(
    (a, b) => Number(cited.has(b.n)) - Number(cited.has(a.n)) || a.n - b.n,
  )

  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pt-5 pb-3">
        <h2 className="text-xs font-medium tracking-wide text-faint uppercase">Sources</h2>
        {message && sources.length > 0 && (
          <p className="mt-1 text-xs text-muted">
            {cited.size > 0 ? `${cited.size} cited` : 'Retrieved'} for “{message.question.slice(0, 60)}
            {message.question.length > 60 ? '…' : ''}”
          </p>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-5">
        {!message || sources.length === 0 ? (
          <div className="mt-6 flex flex-col items-center px-4 text-center text-sm text-muted">
            <BookOpen size={20} className="mb-2 text-faint" aria-hidden />
            Click a citation number in an answer to see the exact passage and open its page.
          </div>
        ) : (
          <ul className="space-y-2.5">
            {sources.map((s) => (
              <SourceCard
                key={s.n}
                ref={(el) => {
                  if (el) refs.current.set(s.n, el)
                  else refs.current.delete(s.n)
                }}
                source={s}
                cited={cited.size === 0 || cited.has(s.n)}
                active={activeSource === s.n}
                onSelect={() => onSelect(s.n)}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
