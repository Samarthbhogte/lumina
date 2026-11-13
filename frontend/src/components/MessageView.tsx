'use client'

import { Check, ChevronDown, Copy, FileDown, RotateCcw, TriangleAlert } from 'lucide-react'
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { answerExportUrl } from '@/lib/api'

import { AnswerMarkdown } from './AnswerMarkdown'
import { ConfidenceBadge } from './ConfidenceBadge'
import { SourceCard } from './SourceCard'
import type { AssistantMessage, Message } from './types'
import { useWorkspaceId } from './WorkspaceContext'

interface Props {
  message: Message
  activeSource: number | null // null unless this message is the one shown in the sources panel
  canRetry: boolean
  onCite: (messageId: string, n: number) => void
  onRetry: (message: AssistantMessage) => void
}

function MessageViewImpl({ message, activeSource, canRetry, onCite, onRetry }: Props) {
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
      activeSource={activeSource}
      canRetry={canRetry}
      onCite={onCite}
      onRetry={onRetry}
    />
  )
}

export const MessageView = memo(MessageViewImpl)

function AssistantView({ message, activeSource, canRetry, onCite, onRetry }: Props & { message: AssistantMessage }) {
  const ws = useWorkspaceId()
  const [copied, setCopied] = useState(false)
  const [showSources, setShowSources] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])

  const valid = useMemo(() => new Map(message.sources.map((s) => [s.n, s.label])), [message.sources])
  const cited = useMemo(() => new Set(message.result?.cited ?? []), [message.result])
  const cite = useCallback((n: number) => onCite(message.id, n), [onCite, message.id])
  const streaming = message.status === 'streaming'
  const sourceCount = cited.size || message.sources.length

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard blocked */
    }
  }

  return (
    <article aria-busy={streaming} className="group">
      <p className="mb-1.5 text-xs font-medium tracking-wide text-faint uppercase">Lumina</p>

      {streaming && !message.content ? (
        <p className="flex items-center gap-2 text-sm text-muted">
          <span aria-hidden className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
          {message.sources.length ? `Reading ${message.sources.length} passages…` : 'Searching your documents…'}
        </p>
      ) : (
        <AnswerMarkdown
          text={message.content}
          validSources={valid}
          activeSource={activeSource}
          onCite={cite}
          streaming={streaming}
        />
      )}

      {message.stopped && <p className="mt-2 text-sm text-muted italic">Stopped before the answer finished.</p>}

      {message.status === 'error' && (
        <div
          role="alert"
          className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-bad/30 bg-bad-soft px-3 py-2 text-sm text-bad"
        >
          <TriangleAlert size={15} aria-hidden />
          <span className="flex-1">{message.error}</span>
          {canRetry && (
            <button
              type="button"
              onClick={() => onRetry(message)}
              className="inline-flex min-h-6 items-center gap-1 rounded px-2 py-1 font-medium hover:bg-bad/10"
            >
              <RotateCcw size={13} aria-hidden /> Retry
            </button>
          )}
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
              className="inline-flex min-h-6 items-center gap-1 rounded-full px-2.5 py-1 text-xs text-muted hover:bg-surface-2 hover:text-ink xl:hidden"
            >
              {sourceCount} source{sourceCount === 1 ? '' : 's'}
              <ChevronDown size={13} aria-hidden className={showSources ? 'rotate-180' : ''} />
            </button>
          )}
          <button
            type="button"
            onClick={copy}
            className="ml-auto inline-flex min-h-6 items-center gap-1 rounded-full px-2.5 py-1 text-xs text-muted hover:bg-surface-2 hover:text-ink focus-visible:opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100"
          >
            {copied ? <Check size={13} aria-hidden /> : <Copy size={13} aria-hidden />}
            <span aria-live="polite">{copied ? 'Copied' : 'Copy'}</span>
          </button>
          {message.result.message_id && (
            <a
              href={answerExportUrl(ws, message.result.message_id)}
              download
              title="Download this answer with its cited passages as an audit-ready PDF"
              className="inline-flex min-h-6 items-center gap-1 rounded-full px-2.5 py-1 text-xs text-muted hover:bg-surface-2 hover:text-ink focus-visible:opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100"
            >
              <FileDown size={13} aria-hidden /> Evidence PDF
            </a>
          )}
        </div>
      )}

      {showSources && (
        <ul className="mt-3 space-y-2 xl:hidden">
          {message.sources.map((s) => (
            <SourceCard
              key={s.n}
              source={s}
              cited={cited.size === 0 || cited.has(s.n)}
              active={activeSource === s.n}
              onSelect={() => cite(s.n)}
            />
          ))}
        </ul>
      )}
    </article>
  )
}
