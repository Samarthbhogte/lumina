'use client'

import { ExternalLink } from 'lucide-react'
import { forwardRef } from 'react'

import { documentFileUrl, type Source } from '@/lib/api'
import { cn } from '@/lib/utils'

interface Props {
  source: Source
  cited: boolean
  active: boolean
  onSelect?: () => void
}

export const SourceCard = forwardRef<HTMLLIElement, Props>(function SourceCard(
  { source, cited, active, onSelect },
  ref,
) {
  return (
    <li
      ref={ref}
      className={cn(
        'rounded-lg border bg-surface p-3 transition-colors',
        active ? 'border-accent ring-1 ring-accent' : 'border-line',
        !cited && 'opacity-75',
      )}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={onSelect}
          aria-label={`Source ${source.n}`}
          aria-pressed={active}
          className={cn(
            'grid h-6 min-w-6 place-items-center rounded px-1 font-mono text-[11px] font-semibold',
            cited ? 'bg-accent-soft text-accent' : 'bg-surface-2 text-muted',
          )}
        >
          {source.n}
        </button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={source.filename}>
            {source.filename}
          </p>
          <p className="text-xs text-muted">
            Page {source.page}
            {!cited && ' · retrieved, not cited'}
          </p>
        </div>
        <a
          href={documentFileUrl(source.document_id, source.page)}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-6 shrink-0 items-center gap-1 rounded px-1.5 py-1 text-xs text-muted hover:bg-surface-2 hover:text-ink"
        >
          Open page <ExternalLink size={12} aria-hidden />
          <span className="sr-only">{`${source.filename}, page ${source.page}, in a new tab`}</span>
        </a>
      </div>
      <blockquote className="mt-2 line-clamp-6 border-l-2 border-line pl-3 font-serif text-[0.9rem] leading-relaxed text-muted">
        {source.snippet}
      </blockquote>
    </li>
  )
})
