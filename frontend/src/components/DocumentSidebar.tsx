'use client'

import { ExternalLink, FileText, LoaderCircle, Trash2, TriangleAlert, Upload, X } from 'lucide-react'
import { useId, useRef, useState } from 'react'

import { documentFileUrl, type DocumentInfo, type Health } from '@/lib/api'
import { cn } from '@/lib/utils'

import { ThemeToggle } from './ThemeToggle'
import { useWorkspaceId } from './WorkspaceContext'

interface Props {
  documents: DocumentInfo[] | null
  loadError: string | null
  health: Health | null
  selected: Set<string>
  uploading: string[]
  onToggle: (id: string) => void
  onClearSelection: () => void
  onUpload: (files: File[]) => void
  onDelete: (doc: DocumentInfo) => void
  onRetryLoad: () => void
  onClose?: () => void
  canEdit: boolean // viewers can read and ask, not upload or delete
  workspaceSlot?: React.ReactNode // workspace switcher, under the brand
  chatsSlot?: React.ReactNode // conversation list, above the documents
  footerSlot?: React.ReactNode // account menu
}

const formatSize = (bytes: number) =>
  bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1048576).toFixed(1)} MB`

export function DocumentSidebar(props: Props) {
  const { documents, loadError, health, selected, uploading, onToggle, onClearSelection } = props
  const [dragging, setDragging] = useState(false)
  const [confirming, setConfirming] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const deleteButtons = useRef(new Map<string, HTMLButtonElement>())
  const idPrefix = useId() // the sidebar renders twice (desktop + drawer), so ids must differ
  const aiOff = health !== null && !health.ai_configured
  const ws = useWorkspaceId()

  const take = (list: FileList | null) => {
    const files = Array.from(list ?? [])
    if (files.length) props.onUpload(files)
  }

  const count = documents?.length ?? 0
  const scope =
    selected.size === 0
      ? `Searching all ${count} document${count === 1 ? '' : 's'}`
      : `Searching ${selected.size} of ${count}`

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-5 pt-5 pb-4">
        <div className="flex items-center gap-2">
          <span aria-hidden className="grid h-7 w-7 place-items-center rounded-md bg-ink font-serif text-lg font-semibold text-paper">
            L
          </span>
          <span className="text-[15px] font-semibold tracking-tight">Lumina</span>
        </div>
        {props.onClose && (
          <button
            type="button"
            onClick={props.onClose}
            aria-label="Close document library"
            className="grid h-8 w-8 place-items-center rounded-md text-muted hover:bg-surface-2 lg:hidden"
          >
            <X size={16} aria-hidden />
          </button>
        )}
      </div>

      {props.workspaceSlot}

      <div className="px-4" hidden={!props.canEdit}>
        <button
          type="button"
          disabled={aiOff}
          onClick={() => input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            if (!aiOff) take(e.dataTransfer.files)
          }}
          className={cn(
            'flex w-full flex-col items-center gap-1 rounded-xl border border-dashed px-4 py-5 text-center transition-colors',
            dragging ? 'border-accent bg-accent-soft' : 'border-line hover:border-faint hover:bg-surface-2',
            aiOff && 'cursor-not-allowed opacity-60',
          )}
        >
          <Upload size={18} className="text-accent" aria-hidden />
          <span className="text-sm font-medium">Add policy PDFs</span>
          <span className="text-xs text-muted">Drop files here or browse</span>
        </button>
        <input
          ref={input}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          onChange={(e) => {
            take(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      {props.chatsSlot}

      <div className="mt-5 flex items-baseline justify-between px-5">
        <h2
          id={`${idPrefix}-heading`}
          tabIndex={-1}
          className="text-xs font-medium tracking-wide text-faint uppercase outline-none"
        >
          Documents
        </h2>
        {selected.size > 0 && (
          <button type="button" onClick={onClearSelection} className="-my-1 rounded px-2 py-1 text-xs text-accent hover:underline">
            Search all
          </button>
        )}
      </div>

      <div className="mt-2 min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        <p className="sr-only" role="status">
          {uploading.length ? `Indexing ${uploading.length} file${uploading.length === 1 ? '' : 's'}` : ''}
        </p>
        {uploading.map((name) => (
          <div key={name} className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm text-muted">
            <LoaderCircle size={15} className="shrink-0 animate-spin text-accent" aria-hidden />
            <span className="truncate">{name}</span>
            <span className="ml-auto shrink-0 text-xs">Indexing</span>
          </div>
        ))}

        {loadError ? (
          <div className="mx-2 mt-1 rounded-lg bg-bad-soft p-3 text-sm text-bad">
            <p className="flex items-center gap-1.5 font-medium">
              <TriangleAlert size={14} aria-hidden /> Couldn’t load documents
            </p>
            <p className="mt-1 text-xs">{loadError}</p>
            <button type="button" onClick={props.onRetryLoad} className="-mx-2 mt-1 rounded px-2 py-1 text-xs font-medium underline">
              Try again
            </button>
          </div>
        ) : documents === null ? (
          <div className="space-y-2 px-2 pt-1" role="status" aria-label="Loading documents">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-9 animate-pulse rounded-md bg-surface-2" />
            ))}
          </div>
        ) : documents.length === 0 && uploading.length === 0 ? (
          <p className="px-2 py-3 text-sm text-muted">
            No documents yet. Add a policy, contract or regulation to start asking questions.
          </p>
        ) : (
          <ul className="space-y-0.5">
            {documents.map((doc) => (
              <li
                key={doc.id}
                className={cn(
                  'group flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-surface-2',
                  selected.has(doc.id) && 'bg-surface-2',
                )}
              >
                {confirming === doc.id ? (
                  <div role="group" aria-label="Confirm delete" className="flex w-full items-center gap-2 py-0.5 text-sm">
                    <span className="min-w-0 flex-1 truncate">Delete “{doc.filename}”?</span>
                    <button
                      type="button"
                      onClick={() => {
                        setConfirming(null)
                        props.onDelete(doc)
                        // The row is about to disappear; keep keyboard focus in the list.
                        document.getElementById(`${idPrefix}-heading`)?.focus()
                      }}
                      className="rounded bg-bad px-2 py-1 text-xs font-medium text-paper"
                    >
                      Delete
                    </button>
                    <button
                      type="button"
                      autoFocus
                      onClick={() => {
                        setConfirming(null)
                        requestAnimationFrame(() => deleteButtons.current.get(doc.id)?.focus())
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Escape') {
                          setConfirming(null)
                          requestAnimationFrame(() => deleteButtons.current.get(doc.id)?.focus())
                        }
                      }}
                      className="rounded px-2 py-1 text-xs text-muted hover:text-ink"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <>
                    <input
                      type="checkbox"
                      id={`${idPrefix}-${doc.id}`}
                      checked={selected.has(doc.id)}
                      onChange={() => onToggle(doc.id)}
                      className="h-4 w-4 shrink-0 accent-[var(--accent)]"
                      aria-label={`Only search ${doc.filename}`}
                    />
                    <label htmlFor={`${idPrefix}-${doc.id}`} className="flex min-w-0 flex-1 cursor-pointer items-center gap-2">
                      <FileText size={15} className="shrink-0 text-faint" aria-hidden />
                      <span className="min-w-0">
                        <span className="block truncate text-sm" title={doc.filename}>
                          {doc.filename}
                        </span>
                        <span className="block text-xs text-faint">
                          {doc.pages} page{doc.pages === 1 ? '' : 's'} · {formatSize(doc.size_bytes)}
                        </span>
                      </span>
                    </label>
                    <div className="flex shrink-0 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-focus-within:opacity-100 [@media(hover:hover)]:group-hover:opacity-100">
                      <a
                        href={documentFileUrl(ws, doc.id)}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`Open ${doc.filename}`}
                        className="grid h-7 w-7 place-items-center rounded text-muted hover:bg-surface hover:text-ink"
                      >
                        <ExternalLink size={13} aria-hidden />
                      </a>
                      {props.canEdit && (
                        <button
                          type="button"
                          ref={(el) => {
                            if (el) deleteButtons.current.set(doc.id, el)
                            else deleteButtons.current.delete(doc.id)
                          }}
                          onClick={() => setConfirming(doc.id)}
                          aria-label={`Delete ${doc.filename}`}
                          className="grid h-7 w-7 place-items-center rounded text-muted hover:bg-surface hover:text-bad"
                        >
                          <Trash2 size={13} aria-hidden />
                        </button>
                      )}
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-line px-5 py-3">
        {props.footerSlot}
        {documents && documents.length > 0 && <p className="mb-2 text-xs text-muted">{scope}</p>}
        <div className="flex items-center justify-between gap-2">
          <p className="flex min-w-0 items-center gap-1.5 text-xs text-muted">
            <span
              aria-hidden
              className={cn(
                'h-1.5 w-1.5 shrink-0 rounded-full',
                health === null ? 'bg-faint' : health.ai_configured ? 'bg-good' : 'bg-bad',
              )}
            />
            <span className="truncate">
              {health === null
                ? 'Connecting…'
                : health.ai_configured
                  ? health.chat_model
                  : `${health.provider} key missing`}
            </span>
          </p>
          <ThemeToggle />
        </div>
      </div>
    </div>
  )
}
