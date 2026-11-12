'use client'

import { Menu, SquarePen, Upload } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import {
  askStream,
  deleteDocument,
  getHealth,
  listDocuments,
  uploadDocuments,
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

const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.')
const newId = () => crypto.randomUUID()

function loadConversation(): Message[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const messages: Message[] = raw ? JSON.parse(raw) : []
    // An answer that was mid-stream when the tab closed can't resume.
    return messages.map((m) =>
      m.role === 'assistant' && m.status === 'streaming'
        ? { ...m, status: 'error', error: 'This answer was interrupted.' }
        : m,
    )
  } catch {
    return []
  }
}

function toHistory(messages: Message[]): HistoryMessage[] {
  return messages
    .filter((m) => m.role === 'user' || (m.status === 'done' && m.content))
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

  const abortRef = useRef<AbortController | null>(null)
  const threadRef = useRef<HTMLDivElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const busy = messages.some((m) => m.role === 'assistant' && m.status === 'streaming')
  const aiOff = health !== null && !health.openai_configured
  const hasDocs = (documents?.length ?? 0) > 0

  const refresh = useCallback(async () => {
    try {
      const [h, docs] = await Promise.all([getHealth(), listDocuments()])
      setHealth(h)
      setDocuments(docs)
      setLoadError(null)
      setSelected((prev) => new Set([...prev].filter((id) => docs.some((d) => d.id === id))))
    } catch (e) {
      setLoadError(errorText(e))
    }
  }, [])

  useEffect(() => {
    void refresh()
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

  // Keep the newest message in view if the reader is already near the bottom.
  useEffect(() => {
    const el = threadRef.current
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 160) el.scrollTop = el.scrollHeight
  }, [messages])

  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setDrawerOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  const patch = (id: string, update: (m: AssistantMessage) => AssistantMessage) =>
    setMessages((prev) => prev.map((m) => (m.id === id && m.role === 'assistant' ? update(m) : m)))

  const ask = async (question: string, retry?: AssistantMessage) => {
    if (busy) return
    const assistantId = retry?.id ?? newId()
    const fresh: AssistantMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      status: 'streaming',
      question,
      sources: [],
    }
    const prior = retry ? messages.slice(0, messages.findIndex((m) => m.id === retry.id) - 1) : messages
    setMessages((prev) =>
      retry
        ? prev.map((m) => (m.id === retry.id ? fresh : m))
        : [...prev, { id: newId(), role: 'user', content: question }, fresh],
    )
    setActive({ messageId: assistantId, n: null })

    const controller = new AbortController()
    abortRef.current = controller
    try {
      await askStream(
        {
          question,
          history: toHistory(prior),
          document_ids: selected.size ? [...selected] : undefined,
        },
        {
          onSources: (sources) => patch(assistantId, (m) => ({ ...m, sources })),
          onToken: (text) => patch(assistantId, (m) => ({ ...m, content: m.content + text })),
          onDone: (result) =>
            patch(assistantId, (m) => ({
              ...m,
              content: result.answer,
              sources: result.sources,
              result,
              status: 'done',
            })),
        },
        controller.signal,
      )
    } catch (e) {
      const stopped = (e as Error).name === 'AbortError'
      patch(assistantId, (m) =>
        stopped && m.content
          ? { ...m, content: `${m.content}\n\n*Stopped.*`, status: 'done' }
          : { ...m, status: 'error', error: stopped ? 'Stopped before an answer arrived.' : errorText(e) },
      )
    } finally {
      abortRef.current = null
    }
  }

  const upload = async (files: File[]) => {
    const pdfs = files.filter((f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'))
    if (pdfs.length < files.length) toast.error('Only PDF files can be added.')
    if (!pdfs.length) return
    setUploading(pdfs.map((f) => f.name))
    try {
      const { results } = await uploadDocuments(pdfs)
      for (const r of results) {
        if (r.status === 'indexed')
          toast.success(`Added ${r.filename}`, { description: `${r.document?.pages} pages indexed` })
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

  const activeMessage = useMemo(() => {
    const id = active?.messageId
    const found = messages.find((m): m is AssistantMessage => m.role === 'assistant' && m.id === id)
    return found ?? [...messages].reverse().find((m): m is AssistantMessage => m.role === 'assistant') ?? null
  }, [messages, active])

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
      <aside className="hidden w-72 shrink-0 border-r border-line bg-surface lg:block">{sidebar()}</aside>

      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Document library">
          <button
            type="button"
            aria-label="Close document library"
            className="absolute inset-0 bg-ink/30"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 w-[85%] max-w-80 border-r border-line bg-surface shadow-xl">
            {sidebar(() => setDrawerOpen(false))}
          </div>
        </div>
      )}

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

        <div ref={threadRef} className="min-h-0 flex-1 overflow-y-auto">
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
                    The server has no OpenAI API key. Add <code className="font-mono">OPENAI_API_KEY</code> to{' '}
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
                    <p className="text-xs font-medium tracking-wide text-faint uppercase">Try asking</p>
                    <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                      {SUGGESTIONS.map((s) => (
                        <li key={s}>
                          <button
                            type="button"
                            onClick={() => void ask(s)}
                            className="h-full w-full rounded-xl border border-line bg-surface px-4 py-3 text-left text-sm hover:border-faint"
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
              <div className="space-y-8" aria-live="polite" aria-relevant="additions">
                {messages.map((m) => (
                  <MessageView
                    key={m.id}
                    message={m}
                    active={activeMessage?.id === m.id}
                    activeSource={activeMessage?.id === m.id ? (active?.n ?? null) : null}
                    onCite={(messageId, n) => setActive({ messageId, n })}
                    onRetry={(failed) => void ask(failed.question, failed)}
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
              disabledReason={aiOff ? 'The server needs an OpenAI API key' : 'Add a PDF to start asking questions'}
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

      <aside className="hidden w-[22rem] shrink-0 border-l border-line bg-surface xl:block">
        <SourcesPanel
          message={activeMessage}
          activeSource={active?.messageId === activeMessage?.id ? (active?.n ?? null) : null}
          onSelect={(n) => activeMessage && setActive({ messageId: activeMessage.id, n })}
        />
      </aside>
    </div>
  )
}
