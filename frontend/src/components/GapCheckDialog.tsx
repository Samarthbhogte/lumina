'use client'

import { CircleCheck, CircleHelp, CircleMinus, Play, RotateCw, TriangleAlert, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import {
  estimateComparison,
  getComparison,
  listComparisons,
  resumeComparison,
  runComparison,
  type Comparison,
  type DocumentInfo,
  type GapStatus,
} from '@/lib/api'
import { cn } from '@/lib/utils'

const STATUS: Record<GapStatus, { label: string; cls: string; Icon: typeof CircleCheck }> = {
  addressed: { label: 'Addressed', cls: 'bg-good-soft text-good', Icon: CircleCheck },
  partial: { label: 'Partially addressed', cls: 'bg-warn-soft text-warn', Icon: CircleHelp },
  needs_review: { label: 'Needs review', cls: 'bg-bad-soft text-bad', Icon: TriangleAlert },
  not_found: { label: 'No matching passage', cls: 'bg-surface-2 text-muted', Icon: CircleMinus },
}

const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.')

interface Props {
  workspaceId: string
  documents: DocumentInfo[]
  open: boolean
  onClose: () => void
  onUsedQuota: () => void
}

export function GapCheckDialog({ workspaceId, documents, open, onClose, onUsedQuota }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [requirements, setRequirements] = useState('')
  const [policy, setPolicy] = useState('')
  const [estimate, setEstimate] = useState<{ requirements: number; max_ai_requests: number; questions_left_today: number } | null>(null)
  const [result, setResult] = useState<Comparison | null>(null)
  const [history, setHistory] = useState<Comparison[]>([])
  const [running, setRunning] = useState(false)
  const [announce, setAnnounce] = useState('')
  const resultsHeading = useRef<HTMLHeadingElement>(null)

  const loadHistory = useCallback(() => {
    listComparisons(workspaceId).then(setHistory).catch(() => setHistory([]))
  }, [workspaceId])

  useEffect(() => {
    const el = dialog.current
    if (!el) return
    if (open && !el.open) {
      el.showModal()
      loadHistory()
    } else if (!open && el.open) el.close()
  }, [open, loadHistory])

  useEffect(() => {
    if (!requirements || !policy || requirements === policy) return
    let live = true
    estimateComparison(workspaceId, { requirements_document_id: requirements, policy_document_id: policy })
      .then((e) => live && setEstimate(e))
      .catch((e) => live && toast.error(errorText(e)))
    return () => {
      live = false
    }
  }, [workspaceId, requirements, policy])

  const go = async (action: () => Promise<Comparison>) => {
    if (running) return
    setRunning(true)
    setAnnounce('Checking requirements…')
    try {
      const done = await action()
      setResult(done)
      setAnnounce(
        done.status === 'partial'
          ? `Stopped early: ${done.rows?.length ?? 0} of ${done.total_requirements} checked. ${done.note ?? ''}`
          : `Done: ${done.summary?.headline ?? 'finished'}.`,
      )
      requestAnimationFrame(() => resultsHeading.current?.focus())
      loadHistory()
    } catch (e) {
      setAnnounce(`The gap check failed: ${errorText(e)}`)
      toast.error('The gap check failed', { description: errorText(e) })
    } finally {
      setRunning(false)
      onUsedQuota()
    }
  }

  const pairReady = requirements && policy && requirements !== policy

  return (
    <dialog
      ref={dialog}
      aria-labelledby="gap-title"
      onClose={onClose}
      className="m-auto w-[min(56rem,calc(100%-2rem))] rounded-2xl border border-line bg-surface p-0 text-ink shadow-xl backdrop:bg-ink/30"
    >
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <h2 id="gap-title" className="text-base font-semibold">
            Gap check
          </h2>
          <p className="text-xs text-muted">Which requirements of one document does another address? Evidence, not a compliance verdict.</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="grid h-8 w-8 place-items-center rounded-md text-muted hover:bg-surface-2">
          <X size={16} aria-hidden />
        </button>
      </div>

      <div className="max-h-[75vh] overflow-y-auto px-5 py-4">
        <p role="status" className="sr-only">
          {announce}
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          {(
            [
              ['gap-req', 'Requirements (e.g. a regulation)', requirements, setRequirements],
              ['gap-pol', 'Checked against (e.g. your policy)', policy, setPolicy],
            ] as const
          ).map(([id, label, value, set]) => (
            <div key={id}>
              <label htmlFor={id} className="block text-sm font-medium">
                {label}
              </label>
              <select
                id={id}
                autoFocus={id === 'gap-req'}
                value={value}
                onChange={(e) => {
                  set(e.target.value)
                  setEstimate(null)
                }}
                className="mt-1 w-full rounded-md border border-field bg-surface px-2 py-1.5 text-sm"
              >
                <option value="">Choose a document…</option>
                {documents.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.filename}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted" aria-live="polite">
            {!pairReady
              ? 'Pick two different documents.'
              : estimate
                ? `${estimate.requirements} requirements · up to ${estimate.max_ai_requests} AI request${estimate.max_ai_requests === 1 ? '' : 's'} (you have ${estimate.questions_left_today} left today)`
                : 'Estimating…'}
          </p>
          <button
            type="button"
            disabled={!pairReady || !estimate || estimate.requirements === 0}
            aria-disabled={running}
            onClick={() => go(() => runComparison(workspaceId, { requirements_document_id: requirements, policy_document_id: policy }))}
            className="inline-flex items-center gap-1.5 rounded-md bg-ink px-3 py-1.5 text-sm font-medium text-paper hover:opacity-90 disabled:opacity-50"
          >
            <Play size={14} aria-hidden /> {running ? 'Checking…' : 'Run gap check'}
          </button>
        </div>

        {result && (
          <section className="mt-5" aria-label="Gap check results">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 ref={resultsHeading} tabIndex={-1} className="font-medium outline-none">
                {result.title}
              </h3>
              {result.summary && <p className="text-sm text-muted">{result.summary.headline}</p>}
            </div>
            {result.status === 'partial' && (
              <div className="mt-2 flex flex-wrap items-center gap-3 rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">
                <span className="flex-1">
                  Stopped early: {result.note} {(result.rows?.length ?? 0)} of {result.total_requirements} checked; progress is saved.
                </span>
                <button type="button" aria-disabled={running} onClick={() => go(() => resumeComparison(workspaceId, result.id))} className="inline-flex items-center gap-1 font-medium underline">
                  <RotateCw size={13} aria-hidden /> Resume
                </button>
              </div>
            )}
            <div className="mt-3 overflow-x-auto" role="region" aria-label="Gap check results table" tabIndex={0}>
            <table className="w-full min-w-[34rem] border-collapse text-sm">
              <caption className="sr-only">Requirement-by-requirement results</caption>
              <thead>
                <tr className="border-b border-line text-left text-xs text-faint uppercase">
                  <th scope="col" className="py-2 pr-3 font-medium">Requirement</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Status</th>
                  <th scope="col" className="py-2 font-medium">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {result.rows?.map((r) => {
                  const st = STATUS[r.status]
                  return (
                    <tr key={r.requirement.id} className="border-b border-line align-top">
                      <td className="py-2 pr-3">
                        <span className="font-mono text-xs text-accent">§{r.requirement.id}</span>{' '}
                        <span className="text-ink">{r.requirement.text}</span>
                      </td>
                      <td className="py-2 pr-3">
                        <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap', st.cls)}>
                          <st.Icon size={12} aria-hidden /> {st.label}
                        </span>
                      </td>
                      <td className="py-2 text-muted">
                        {r.match && r.status !== 'not_found' && <p className="text-xs font-medium text-ink">{r.match.label}</p>}
                        {r.quote && <p className="font-serif">“{r.quote}”</p>}
                        {r.rationale && <p className="text-xs">{r.rationale}</p>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            </div>
          </section>
        )}

        {history.length > 0 && (
          <section className="mt-6">
            <h3 className="text-xs font-medium tracking-wide text-faint uppercase">Previous checks</h3>
            <ul className="mt-2 space-y-1">
              {history.map((h) => (
                <li key={h.id}>
                  <button
                    type="button"
                    onClick={() => getComparison(workspaceId, h.id).then(setResult).catch((e) => toast.error(errorText(e)))}
                    className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm hover:bg-surface-2"
                  >
                    <span className="truncate">{h.title}</span>
                    <span className="shrink-0 text-xs text-muted">{h.summary?.headline ?? h.status}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </dialog>
  )
}
