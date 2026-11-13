'use client'

import { useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

export function AuthShell({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-2">
          <span aria-hidden className="grid h-8 w-8 place-items-center rounded-md bg-ink font-serif text-xl font-semibold text-paper">
            L
          </span>
          <span className="text-base font-semibold tracking-tight">Lumina</span>
        </div>
        <h1 className="font-serif text-3xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-2 text-sm text-muted">{subtitle}</p>}
        <div className="mt-6">{children}</div>
      </div>
    </main>
  )
}

export function Field({
  label,
  hint,
  ...input
}: { label: string; hint?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = `f-${input.name}`
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        {...input}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className="block w-full rounded-lg border border-field bg-surface px-3 py-2 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/40"
      />
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-muted">
          {hint}
        </p>
      )}
    </div>
  )
}

export function useSubmit<T>(action: (form: FormData) => Promise<T>, onDone: (value: T) => void) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      onDone(await action(new FormData(e.currentTarget)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }
  return { submit, error, busy }
}

export function SubmitButton({ busy, children }: { busy: boolean; children: React.ReactNode }) {
  return (
    <button
      type="submit"
      aria-disabled={busy} /* stays focusable while busy; useSubmit ignores repeat submits */
      className={cn(
        'w-full rounded-lg bg-ink px-4 py-2.5 text-sm font-medium text-paper hover:opacity-90',
        busy && 'cursor-wait opacity-70',
      )}
    >
      {children}
    </button>
  )
}

export function FormError({ error }: { error: string | null }) {
  const ref = useRef<HTMLParagraphElement>(null)
  useEffect(() => {
    if (error) ref.current?.focus() // so the next Tab continues from the problem, not the page top
  }, [error])
  if (!error) return null
  return (
    <p ref={ref} id="form-error" tabIndex={-1} role="alert" className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad outline-none">
      {error}
    </p>
  )
}

export const PASSWORD_HINT = 'At least 15 characters. A short phrase of four or five words works well.'
