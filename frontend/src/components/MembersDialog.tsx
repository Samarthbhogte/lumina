'use client'

import { Copy, Link2, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import {
  createInvite,
  listInvites,
  listMembers,
  removeMember,
  revokeInvite,
  setMemberRole,
  type Invite,
  type Member,
  type Role,
} from '@/lib/api'

const ROLES: Role[] = ['viewer', 'editor', 'owner']
const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.')

export function MembersDialog({ workspaceId, open, onClose }: { workspaceId: string; open: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [members, setMembers] = useState<Member[]>([])
  const [invites, setInvites] = useState<Invite[]>([])
  const [role, setRole] = useState<Role>('viewer')
  const [link, setLink] = useState<string | null>(null)
  const [pending, setPending] = useState<Record<string, Role>>({})

  const load = useCallback(async () => {
    try {
      const [m, i] = await Promise.all([listMembers(workspaceId), listInvites(workspaceId)])
      setMembers(m)
      setInvites(i)
    } catch (e) {
      toast.error('Couldn’t load members', { description: errorText(e) })
    }
  }, [workspaceId])

  useEffect(() => {
    const el = dialog.current
    if (!el) return
    if (open && !el.open) {
      el.showModal()
      void load()
    } else if (!open && el.open) el.close()
  }, [open, load])

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn()
    } catch (e) {
      toast.error(errorText(e))
    }
    void load()
  }

  return (
    <dialog
      ref={dialog}
      aria-labelledby="members-title"
      onClose={onClose}
      className="m-auto w-[min(32rem,calc(100%-2rem))] rounded-2xl border border-line bg-surface p-0 text-ink shadow-xl backdrop:bg-ink/30"
    >
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <h2 id="members-title" className="text-base font-semibold">
          Members &amp; invites
        </h2>
        <button type="button" onClick={onClose} aria-label="Close" className="grid h-8 w-8 place-items-center rounded-md text-muted hover:bg-surface-2">
          <X size={16} aria-hidden />
        </button>
      </div>
      <div className="max-h-[70vh] space-y-6 overflow-y-auto px-5 py-4">
        <section>
          <h3 className="text-xs font-medium tracking-wide text-faint uppercase">Invite someone</h3>
          <div className="mt-2 flex gap-2">
            <label htmlFor="invite-role" className="sr-only">
              Role for the invite
            </label>
            <select id="invite-role" autoFocus value={role} onChange={(e) => setRole(e.target.value as Role)} className="rounded-md border border-field bg-surface px-2 py-1.5 text-sm">
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() =>
                act(async () => {
                  const inv = await createInvite(workspaceId, role)
                  setLink(inv.link ?? null)
                })
              }
              className="inline-flex items-center gap-1.5 rounded-md bg-ink px-3 py-1.5 text-sm font-medium text-paper hover:opacity-90"
            >
              <Link2 size={14} aria-hidden /> Create invite link
            </button>
          </div>
          {link && (
            <div className="mt-3 rounded-lg bg-surface-2 p-3">
              <p className="text-xs text-muted">Send this link to the person you’re inviting. It works once and expires in 7 days.</p>
              <div className="mt-2 flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate font-mono text-xs">{link}</code>
                <button
                  type="button"
                  onClick={() => navigator.clipboard.writeText(link).then(() => toast('Invite link copied'))}
                  className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-accent hover:underline"
                >
                  <Copy size={12} aria-hidden /> Copy
                </button>
              </div>
            </div>
          )}
          {invites.length > 0 && (
            <ul className="mt-3 space-y-1 text-sm">
              {invites.map((i) => (
                <li key={i.id} className="flex items-center justify-between rounded-md px-2 py-1 hover:bg-surface-2">
                  <span>
                    Pending {i.role} invite · expires {new Date(i.expires_at).toLocaleDateString()}
                  </span>
                  <button type="button" onClick={() => act(() => revokeInvite(workspaceId, i.id))} className="text-xs text-bad hover:underline">
                    Revoke
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h3 className="text-xs font-medium tracking-wide text-faint uppercase">Members</h3>
          <ul className="mt-2 space-y-1">
            {members.map((m) => (
              <li key={m.user_id} className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-surface-2">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{m.display_name}</span>
                  <span className="block truncate text-xs text-muted">{m.email}</span>
                </span>
                <label htmlFor={`role-${m.user_id}`} className="sr-only">
                  Role for {m.display_name}
                </label>
                <select
                  id={`role-${m.user_id}`}
                  value={pending[m.user_id] ?? m.role}
                  onChange={(e) => setPending((p) => ({ ...p, [m.user_id]: e.target.value as Role }))}
                  className="rounded-md border border-field bg-surface px-2 py-1 text-xs"
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
                {pending[m.user_id] && pending[m.user_id] !== m.role && (
                  <button
                    type="button"
                    onClick={() => {
                      const role = pending[m.user_id]
                      if (m.role === 'owner' && !window.confirm(`Remove owner rights from ${m.display_name}?`)) return
                      setPending((p) => Object.fromEntries(Object.entries(p).filter(([k]) => k !== m.user_id)))
                      void act(() => setMemberRole(workspaceId, m.user_id, role))
                    }}
                    className="rounded-md bg-ink px-2 py-1 text-xs font-medium text-paper hover:opacity-90"
                  >
                    Save
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => window.confirm(`Remove ${m.display_name} from this workspace?`) && act(() => removeMember(workspaceId, m.user_id))}
                  aria-label={`Remove ${m.display_name}`}
                  className="grid h-7 w-7 place-items-center rounded text-muted hover:text-bad"
                >
                  <Trash2 size={13} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </dialog>
  )
}
