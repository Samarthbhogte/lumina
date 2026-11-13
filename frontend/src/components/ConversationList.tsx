'use client'

import { MessageSquare, SquarePen, Trash2 } from 'lucide-react'

import type { Conversation } from '@/lib/api'
import { cn } from '@/lib/utils'

interface Props {
  conversations: Conversation[]
  activeId: string | null
  busy: boolean
  onOpen: (id: string) => void
  onNew: () => void
  onDelete: (c: Conversation) => void
}

export function ConversationList({ conversations, activeId, busy, onOpen, onNew, onDelete }: Props) {
  return (
    <div className="mt-4">
      <div className="flex items-baseline justify-between px-5">
        <h2 className="text-xs font-medium tracking-wide text-faint uppercase">Chats</h2>
        <button
          type="button"
          onClick={onNew}
          disabled={busy}
          className="-my-1 inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-accent hover:underline disabled:opacity-50"
        >
          <SquarePen size={12} aria-hidden /> New chat
        </button>
      </div>
      {conversations.length === 0 ? (
        <p className="px-5 pt-2 text-xs text-muted">Your questions are saved here.</p>
      ) : (
        <ul className="mt-1 max-h-48 space-y-0.5 overflow-y-auto px-3">
          {conversations.map((c) => (
            <li key={c.id} className="group flex items-center">
              <button
                type="button"
                disabled={busy}
                onClick={() => onOpen(c.id)}
                aria-current={c.id === activeId ? 'true' : undefined}
                className={cn(
                  'flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-surface-2',
                  c.id === activeId && 'bg-surface-2 font-medium',
                )}
              >
                <MessageSquare size={13} className="shrink-0 text-faint" aria-hidden />
                <span className="truncate">{c.title}</span>
              </button>
              <button
                type="button"
                onClick={() => onDelete(c)}
                aria-label={`Delete chat “${c.title}”`}
                className="grid h-7 w-7 shrink-0 place-items-center rounded text-muted hover:text-bad [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-focus-within:opacity-100 [@media(hover:hover)]:group-hover:opacity-100"
              >
                <Trash2 size={13} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
