'use client'

import { Menu, SquarePen, Upload } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import {
  askStream,
  deleteDocument,
  getHealth,
  listDocuments,
  uploadDocuments,
  type AskResult,
  type DocumentInfo,
  type Health,
  type HistoryMessage,
} from '@/lib/api'

import { Composer } from './Composer'
import { DocumentSidebar } from './DocumentSidebar'
import { MessageView } from './MessageView'
import { SourcesPanel } from './SourcesPanel'
import type { AssistantMessage, Message } from './types'

const STORAGE_KEY = 'lumina.conversation.v1'
const HISTORY_TURNS = 8

const SUGGESTIONS = [
  'What is the retention period for personal data?',
  'How quickly must a data breach be reported, and to whom?',
  'How can users withdraw consent?',
  'Summarise the key obligations in these documents.',
]

const CONFIDENCE_LABEL = { high: 'strong source match', medium: 'partial source match', low: 'weak source match' }

const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.')
const isAbort = (e: unknown) => e instanceof Error && e.name === 'AbortError'
const newId = () => crypto.randomUUID()

/** Restore the saved conversation, dropping anything that doesn't look like a message. */
function loadConversation(): Message[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    if (!Array.isArray(parsed)) return []
    return parsed.flatMap((raw): Message[] => {
      const m = raw as Record<string, unknown>
      if (!m || typeof m.id !== 'string' || typeof m.content !== 'string') return []
      if (m.role === 'user') return [{ id: m.id, role: 'user', content: m.content }]
      if (m.role !== 'assistant' || typeof m.question !== 'string') return []
      const status = m.status === 'done' || m.status === 'error' ? m.status : 'error'
      return [
        {
          id: m.id,
          role: 'assistant',
          content: m.content,
          question: m.question,
          status,
          sources: Array.isArray(m.sources) ? m.sources : [],
          result: m.result && typeof m.result === 'object' ? (m.result as AskResult) : undefined,
          error: status === 'error' ? (typeof m.error === 'string' ? m.error : 'This answer was interrupted.') : undefined,
          stopped: m.stopped === true,
        },
      ]
    })
  } catch {
    return []
  }
}

function toHistory(messages: Message[]): HistoryMessage[] {
  return messages
    .filter((m) => m.role === 'user' || (m.status === 'done' && !m.stopped && m.content))
    .slice(-HISTORY_TURNS)
    .map((m) => ({ role: m.role, content: m.content }))
}

export default function Workspace() {
  const [messages, setMessages] = useState<Message[]>(loadConversation)
  const [documents, setDocuments] = useState<DocumentInfo[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [uploading, setUploading] = useState<string[]>([])
  const [active, setActive] = useState<{ messageId: string; n: number | null } | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [announcement, setAnnouncement] = useState('')

  const abortRef = useRef<AbortController | null>(null)
  const messagesRef = useRef(messages)
  const threadRef = useRef<HTMLDivElement>(null)
  const stuckToBottom = useRef(true)
  const fileInput = useRef<HTMLInputElement>(null)
  const drawer = useRef<HTMLDialogElement>(null)
  const refreshId = useRef(0)
  const pendingTokens = useRef('')
  const frame = useRef<number | null>(null)

  const busy = messages.some((m) => m.role === 'assistant' && m.status === 'streaming')
  const aiOff = health !== null && !health.ai_configured
  const hasDocs = (documents?.length ?? 0) > 0

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  const refresh = useCallback(async () => {
    const id = ++refreshId.current
    try {
      const [h, docs] = await Promise.all([getHealth(), listDocuments()])
      if (id !== refreshId.current) return // a newer refresh is in flight
      setHealth(h)
      setDocuments(docs)
      setLoadError(null)
      setSelected((prev) => new Set([...prev].filter((d) => docs.some((doc) => doc.id === d))))
    } catch (e) {
      if (id === refreshId.current) setLoadError(errorText(e))
    }
  }, [])

  useEffect(() => {
    void refresh()
    return () => abortRef.current?.abort() // don't leave a stream running after unmount
  }, [refresh])

  // Persist the conversation (not while streaming, to avoid a write per token).
  useEffect(() => {
    if (busy) return
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-60)))
    } catch {
      /* storage unavailable */
    }
  }, [messages, busy])

  // Follow new content only while the reader is at the bottom of the thread.
  useLayoutEffect(() => {
    const el = threadRef.current
    if (el && stuckToBottom.current) el.scrollTop = el.scrollHeight
  }, [messages])

  // The mobile library is a native modal dialog: it traps focus, closes on Escape and
  // returns focus to the button that opened it.
  useEffect(() => {
    const el = drawer.current
    if (!el) return
    if (drawerOpen && !el.open) el.showModal()
    else if (!drawerOpen && el.open) el.close()
  }, [drawerOpen])

  const patch = useCallback(
    (id: string, update: (m: AssistantMessage) => AssistantMessage) =>
      setMessages((prev) => prev.map((m) => (m.id === id && m.role === 'assistant' ? update(m) : m))),
    [],
  )

  const flushTokens = useCallback(
    (id: string) => {
      if (frame.current !== null) cancelAnimationFrame(frame.current)
      frame.current = null
      const text = pendingTokens.current
      pendingTokens.current = ''
      if (text) patch(id, (m) => ({ ...m, content: m.content + text }))
    },
    [patch],
  )

  const ask = async (question: string, retry?: AssistantMessage) => {
    if (abortRef.current) return // synchronous guard: a stream is already running
    const controller = new AbortController()
    abortRef.current = controller

    const current = messagesRef.current
    let prior = current
    if (retry) {
      const idx = current.findIndex((m) => m.id === retry.id)
      if (idx < 0) {
        abortRef.current = null
        return
      }
      prior = current.slice(0, Math.max(0, idx - 1)) // everything before the question being retried
    }

    const assistantId = retry?.id ?? newId()
    const fresh: AssistantMessage = { id: assistantId, role: 'assistant', content: '', status: 'streaming', question, sources: [] }
    setMessages((prev) =>
      retry
        ? prev.map((m) => (m.id === retry.id ? fresh : m))
        : [...prev, { id: newId(), role: 'user', content: question }, fresh],
    )
    setActive({ messageId: assistantId, n: null })
    setAnnouncement('Generating answer…')
    stuckToBottom.current = true

    const docIds = [...selected].filter((id) => documents?.some((d) => d.id === id))
    try {
      await askStream(
        { question, history: toHistory(prior), document_ids: docIds.length ? docIds : undefined },
        {
          onSources: (sources) => patch(assistantId, (m) => ({ ...m, sources })),
          onToken: (text) => {
            // Batch tokens into one state update per animation frame.
            pendingTokens.current += text
            frame.current ??= requestAnimationFrame(() => flushTokens(assistantId))
          },
          onDone: (result) => {
            if (frame.current !== null) cancelAnimationFrame(frame.current)
            frame.current = null
            pendingTokens.current = ''
            patch(assistantId, (m) => ({ ...m, content: result.answer, sources: result.sources, result, status: 'done' }))
            setAnnouncement(
              result.flagged || !result.found
                ? `Answer ready. ${result.answer}`
                : `Answer ready, ${result.cited.length} source${result.cited.length === 1 ? '' : 's'} cited, ${CONFIDENCE_LABEL[result.confidence]}.`,
            )
          },
        },
        controller.signal,
      )
    } catch (e) {
      flushTokens(assistantId)
      const stopped = isAbort(e)
      patch(assistantId, (m) =>
        stopped && m.content
          ? { ...m, status: 'done', stopped: true }
          : { ...m, status: 'error', error: stopped ? 'Stopped before an answer arrived.' : errorText(e) },
      )
      setAnnouncement(stopped ? 'Stopped.' : `Error: ${errorText(e)}`)
    } finally {
      if (abortRef.current === controller) abortRef.current = null
    }
  }

  // Stable callbacks so finished messages don't re-render while another one streams.
  const askRef = useRef(ask)
  useEffect(() => {
    askRef.current = ask
  })
  const onRetry = useCallback((m: AssistantMessage) => void askRef.current(m.question, m), [])
  const onCite = useCallback((messageId: string, n: number) => setActive({ messageId, n }), [])

  const upload = async (files: File[]) => {
    const pdfs = files.filter((f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'))
    if (pdfs.length < files.length) toast.error('Only PDF files can be added.')
    if (!pdfs.length) return
    setUploading(pdfs.map((f) => f.name))
    try {
      const { results } = await uploadDocuments(pdfs)
      for (const r of results) {
        if (r.status === 'indexed') toast.success(`Added ${r.filename}`, { description: `${r.document?.pages} pages indexed` })
        else if (r.status === 'duplicate') toast(`${r.filename} is already in your library`)
        else toast.error(`Couldn’t add ${r.filename}`, { description: r.error ?? undefined })
      }
    } catch (e) {
      toast.error('Upload failed', { description: errorText(e) })
    } finally {
      setUploading([])
      void refresh()
    }
  }

  const remove = async (doc: DocumentInfo) => {
    try {
      await deleteDocument(doc.id)
      toast(`Deleted ${doc.filename}`)
    } catch (e) {
      toast.error(`Couldn’t delete ${doc.filename}`, { description: errorText(e) })
    } finally {
      void refresh()
    }
  }

  const lastAssistantId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === 'assistant') return messages[i].id
    return null
  }, [messages])

  const activeMessage = useMemo(() => {
    const id = active?.messageId ?? lastAssistantId
    return messages.find((m): m is AssistantMessage => m.role === 'assistant' && m.id === id) ?? null
  }, [messages, active, lastAssistantId])
  const activeSource = active && active.messageId === activeMessage?.id ? active.n : null

  const scopeLabel = !hasDocs
    ? 'No documents yet'
    : selected.size
      ? `Searching ${selected.size} selected document${selected.size === 1 ? '' : 's'}`
      : `Searching all ${documents!.length} documents`

  const sidebar = (onClose?: () => void) => (
    <DocumentSidebar
      documents={documents}
      loadError={loadError}
      health={health}
      selected={selected}
      uploading={uploading}
      onToggle={(id) =>
        setSelected((prev) => {
          const next = new Set(prev)
          if (next.has(id)) next.delete(id)
          else next.add(id)
          return next
        })
      }
      onClearSelection={() => setSelected(new Set())}
      onUpload={upload}
      onDelete={remove}
      onRetryLoad={() => {
        setLoadError(null)
        void refresh()
      }}
      onClose={onClose}
    />
  )

  return (
    <div className="flex h-dvh overflow-hidden">
      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>

      <aside aria-label="Document library" className="hidden w-72 shrink-0 border-r border-line bg-surface lg:block">
        {sidebar()}
      </aside>

      <dialog
        ref={drawer}
        aria-label="Document library"
        onClose={() => setDrawerOpen(false)}
        onClick={(e) => e.target === e.currentTarget && setDrawerOpen(false)}
        className="m-0 h-dvh max-h-none w-[85%] max-w-80 border-r border-line bg-surface p-0 text-ink shadow-xl backdrop:bg-ink/30 lg:hidden"
      >
        {drawerOpen && sidebar(() => setDrawerOpen(false))}
      </dialog>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-line px-3 sm:px-5">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              aria-label="Open document library"
              className="grid h-9 w-9 place-items-center rounded-md text-muted hover:bg-surface-2 lg:hidden"
            >
              <Menu size={18} aria-hidden />
            </button>
            <h1 className="text-sm font-medium">
              <span className="lg:hidden">Lumina · </span>Compliance assistant
            </h1>
          </div>
          {messages.length > 0 && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setMessages([])
                setActive(null)
              }}
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-muted hover:bg-surface-2 hover:text-ink disabled:opacity-50"
            >
              <SquarePen size={15} aria-hidden /> New chat
            </button>
          )}
        </header>

        <div
          ref={threadRef}
          onScroll={(e) => {
            const el = e.currentTarget
            stuckToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
          }}
          className="min-h-0 flex-1 overflow-y-auto"
        >
          <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
            {messages.length === 0 ? (
              <div className="mx-auto max-w-xl pt-[8vh]">
                <h2 className="font-serif text-3xl leading-tight font-semibold tracking-tight sm:text-4xl">
                  Ask your policies anything.
                </h2>
                <p className="mt-3 text-muted">
                  Every answer cites the document and page it came from, so you can check it in one click.
                </p>
                {aiOff ? (
                  <p className="mt-6 rounded-lg bg-bad-soft p-3 text-sm text-bad">
                    The server has no {health?.provider} API key. Add it to{' '}
                    <code className="font-mono">backend/.env</code> and restart the API.
                  </p>
                ) : loadError ? (
                  <p className="mt-6 rounded-lg bg-bad-soft p-3 text-sm text-bad">{loadError}</p>
                ) : documents === null ? null : !hasDocs ? (
                  <>
                    <button
                      type="button"
                      onClick={() => fileInput.current?.click()}
                      className="mt-6 inline-flex items-center gap-2 rounded-lg bg-ink px-4 py-2.5 text-sm font-medium text-paper hover:opacity-90"
                    >
                      <Upload size={15} aria-hidden /> Add your first PDF
                    </button>
                    <input
                      ref={fileInput}
                      type="file"
                      accept="application/pdf,.pdf"
                      multiple
                      hidden
                      onChange={(e) => {
                        void upload(Array.from(e.target.files ?? []))
                        e.target.value = ''
                      }}
                    />
                  </>
                ) : (
                  <div className="mt-8">
                    <h3 className="text-xs font-medium tracking-wide text-faint uppercase">Try asking</h3>
                    <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                      {SUGGESTIONS.map((s) => (
                        <li key={s}>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void ask(s)}
                            className="h-full w-full rounded-xl border border-line bg-surface px-4 py-3 text-left text-sm hover:border-field"
                          >
                            {s}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-8">
                {messages.map((m) => (
                  <MessageView
                    key={m.id}
                    message={m}
                    activeSource={activeMessage?.id === m.id ? activeSource : null}
                    canRetry={!busy && m.id === lastAssistantId}
                    onCite={onCite}
                    onRetry={onRetry}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="shrink-0 px-4 pb-4 sm:px-6">
          <div className="mx-auto w-full max-w-3xl">
            <Composer
              busy={busy}
              disabled={aiOff || !hasDocs}
              disabledReason={aiOff ? `The server needs a ${health?.provider ?? 'provider'} API key` : 'Add a PDF to start asking questions'}
              scopeLabel={scopeLabel}
              onSend={(q) => void ask(q)}
              onStop={() => abortRef.current?.abort()}
            />
            <p className="mt-2 text-center text-[11px] text-faint">
              Lumina can be wrong. Check the cited page before relying on an answer.
            </p>
          </div>
        </div>
      </main>

      <aside aria-label="Sources" className="hidden w-[22rem] shrink-0 border-l border-line bg-surface xl:block">
        <SourcesPanel
          message={activeMessage}
          activeSource={activeSource}
          onSelect={(n) => activeMessage && setActive({ messageId: activeMessage.id, n })}
        />
      </aside>
    </div>
  )
}
