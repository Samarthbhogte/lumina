'use client'

import { ExternalLink } from 'lucide-react'
import { forwardRef } from 'react'

import { documentFileUrl, type Source } from '@/lib/api'
import { cn } from '@/lib/utils'

import { useWorkspaceId } from './WorkspaceContext'

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
  const ws = useWorkspaceId()
  // "GDPR Sample Compliance §7.2, pp.1–2" -> name "GDPR Sample Compliance", where "§7.2, pp.1–2".
  const label = source.label || `${source.filename}, p.${source.page}`
  const split = label.search(/ §|, pp?\./)
  const docName = split > 0 ? label.slice(0, split) : label
  const where = split > 0 ? label.slice(split).replace(/^,\s*/, '').trim() : ''
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
          {/* The document name may truncate; the clause and page must always stay visible. */}
          <p className="flex min-w-0 items-baseline gap-1.5 text-sm" title={`${source.label} (${source.filename})`}>
            <span className="truncate font-medium">{docName}</span>
            <span className="shrink-0 font-mono text-xs text-accent">{where}</span>
          </p>
          <p className="truncate text-xs text-muted">
            {source.heading ?? `Page ${source.page}`}
            {source.ocr && (
              <span title="Read from a scanned page by OCR: check the wording against the page itself" className="ml-1.5 rounded bg-warn-soft px-1 py-px text-[10px] font-medium text-warn">
                OCR text<span className="sr-only">: read by OCR from a scanned page, check the wording against the page</span>
              </span>
            )}
            {!cited && ' · retrieved, not cited'}
          </p>
        </div>
        <a
          href={documentFileUrl(ws, source.document_id, source.page)}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-6 shrink-0 items-center gap-1 rounded px-1.5 py-1 text-xs text-muted hover:bg-surface-2 hover:text-ink"
        >
          Open page <ExternalLink size={12} aria-hidden />
          <span className="sr-only">{`${source.filename}, page ${source.page}, in a new tab`}</span>
        </a>
      </div>
      <blockquote className="mt-2 line-clamp-6 border-l-2 border-line pl-3 font-serif text-[0.9rem] leading-relaxed whitespace-pre-line text-muted">
        {source.snippet}
      </blockquote>
    </li>
  )
})
