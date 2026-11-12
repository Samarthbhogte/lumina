'use client'

import { ArrowUp, Square } from 'lucide-react'
import { useRef, useState } from 'react'

import { cn } from '@/lib/utils'

interface Props {
  busy: boolean
  disabled: boolean
  disabledReason?: string
  scopeLabel: string
  onSend: (text: string) => void
  onStop: () => void
}

export function Composer({ busy, disabled, disabledReason, scopeLabel, onSend, onStop }: Props) {
  const [text, setText] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  const resize = () => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }

  const submit = () => {
    const q = text.trim()
    if (!q || busy || disabled) return
    onSend(q)
    setText('')
    requestAnimationFrame(resize)
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      className="rounded-2xl border border-line bg-surface shadow-sm focus-within:border-ring"
    >
      <label htmlFor="question" className="sr-only">
        Ask a question about your documents
      </label>
      <textarea
        id="question"
        ref={ref}
        rows={1}
        value={text}
        disabled={disabled}
        placeholder={disabled ? disabledReason : 'Ask about retention, consent, breach notice…'}
        onChange={(e) => {
          setText(e.target.value)
          resize()
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            submit()
          }
        }}
        className="block max-h-[200px] w-full resize-none bg-transparent px-4 pt-3.5 pb-1 outline-none placeholder:text-faint disabled:cursor-not-allowed"
      />
      <div className="flex items-center justify-between gap-3 px-3 pb-2.5">
        <p className="truncate text-xs text-faint">{scopeLabel}</p>
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop generating"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-ink text-paper hover:opacity-85"
          >
            <Square size={12} fill="currentColor" aria-hidden />
          </button>
        ) : (
          <button
            type="submit"
            aria-label="Send question"
            disabled={disabled || !text.trim()}
            className={cn(
              'grid h-8 w-8 shrink-0 place-items-center rounded-full transition-colors',
              text.trim() && !disabled ? 'bg-ink text-paper hover:opacity-85' : 'bg-surface-2 text-faint',
            )}
          >
            <ArrowUp size={16} aria-hidden />
          </button>
        )}
      </div>
    </form>
  )
}
