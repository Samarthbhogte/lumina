'use client'

import { Check, ChevronDown, Copy, RotateCcw, TriangleAlert } from 'lucide-react'
import { useMemo, useState } from 'react'

import { AnswerMarkdown } from './AnswerMarkdown'
import { ConfidenceBadge } from './ConfidenceBadge'
import { SourceCard } from './SourceCard'
import type { AssistantMessage, Message } from './types'

interface Props {
  message: Message
  active: boolean
  activeSource: number | null
  onCite: (messageId: string, n: number) => void
  onRetry: (message: AssistantMessage) => void
}

export function MessageView({ message, active, activeSource, onCite, onRetry }: Props) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-md bg-surface-2 px-4 py-2.5 whitespace-pre-wrap">
          {message.content}
        </p>
      </div>
    )
  }
  return (
    <AssistantView
      message={message}
      active={active}
      activeSource={activeSource}
      onCite={onCite}
      onRetry={onRetry}
    />
  )
}

function AssistantView({
  message,
  active,
  activeSource,
  onCite,
  onRetry,
}: Props & { message: AssistantMessage }) {
  const [copied, setCopied] = useState(false)
  const [showSources, setShowSources] = useState(false)
  const valid = useMemo(() => new Set(message.sources.map((s) => s.n)), [message.sources])
  const cited = new Set(message.result?.cited ?? [])
  const streaming = message.status === 'streaming'

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard blocked */
    }
  }

  return (
    <article aria-busy={streaming} className="group">
      <p className="mb-1.5 text-xs font-medium tracking-wide text-faint uppercase">Lumina</p>

      {streaming && !message.content ? (
        <p className="flex items-center gap-2 text-sm text-muted" role="status">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
          {message.sources.length
            ? `Reading ${message.sources.length} passages…`
            : 'Searching your documents…'}
        </p>
      ) : (
        <AnswerMarkdown
          text={message.content}
          validSources={valid}
          activeSource={active ? activeSource : null}
          onCite={(n) => onCite(message.id, n)}
          streaming={streaming}
        />
      )}

      {message.status === 'error' && (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-bad/30 bg-bad-soft px-3 py-2 text-sm text-bad">
          <TriangleAlert size={15} aria-hidden />
          <span className="flex-1">{message.error}</span>
          <button
            type="button"
            onClick={() => onRetry(message)}
            className="inline-flex items-center gap-1 rounded px-2 py-1 font-medium hover:bg-bad/10"
          >
            <RotateCcw size={13} aria-hidden /> Retry
          </button>
        </div>
      )}

      {message.result && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <ConfidenceBadge result={message.result} />
          {message.sources.length > 0 && (
            <button
              type="button"
              onClick={() => setShowSources((v) => !v)}
              aria-expanded={showSources}
              className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs text-muted hover:bg-surface-2 hover:text-ink xl:hidden"
            >
              {cited.size || message.sources.length} source{(cited.size || message.sources.length) === 1 ? '' : 's'}
              <ChevronDown size={13} aria-hidden className={showSources ? 'rotate-180' : ''} />
            </button>
          )}
          <button
            type="button"
            onClick={copy}
            className="ml-auto inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs text-muted opacity-100 hover:bg-surface-2 hover:text-ink sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
          >
            {copied ? <Check size={13} aria-hidden /> : <Copy size={13} aria-hidden />}
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      )}

      {showSources && (
        <ul className="mt-3 space-y-2 xl:hidden">
          {message.sources.map((s) => (
            <SourceCard
              key={s.n}
              source={s}
              cited={cited.size === 0 || cited.has(s.n)}
              active={active && activeSource === s.n}
              onSelect={() => onCite(message.id, s.n)}
            />
          ))}
        </ul>
      )}
    </article>
  )
}
