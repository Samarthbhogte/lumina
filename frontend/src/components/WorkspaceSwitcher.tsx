'use client'

import { Plus, Users } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { createWorkspace, type WorkspaceInfo } from '@/lib/api'

interface Props {
  workspaces: WorkspaceInfo[]
  current: WorkspaceInfo
  onManage: () => void
}

export function WorkspaceSwitcher({ workspaces, current, onManage }: Props) {
  const router = useRouter()
  const [creating, setCreating] = useState(false)
  const [choice, setChoice] = useState(current.id)

  const create = async () => {
    const name = window.prompt('Name for the new team workspace', 'Compliance team')?.trim()
    if (!name) return
    setCreating(true)
    try {
      const ws = await createWorkspace(name)
      router.push(`/w/${ws.id}`)
    } catch (e) {
      toast.error('Couldn’t create the workspace', { description: e instanceof Error ? e.message : undefined })
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="px-4 pb-3">
      <label htmlFor="workspace-switcher" className="sr-only">
        Workspace
      </label>
      <div className="flex items-center gap-1.5">
        <select
          id="workspace-switcher"
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
          className="min-w-0 flex-1 truncate rounded-md border border-field bg-surface px-2 py-1.5 text-sm"
        >
          {workspaces.map((w) => (
            <option key={w.id} value={w.id}>
              {w.kind === 'personal' ? `${w.name} (personal)` : w.name}
            </option>
          ))}
        </select>
        {choice !== current.id && (
          <button
            type="button"
            onClick={() => router.push(`/w/${choice}`)}
            className="shrink-0 rounded-md bg-ink px-2 py-1.5 text-xs font-medium text-paper hover:opacity-90"
          >
            Open
          </button>
        )}
        <button
          type="button"
          onClick={create}
          disabled={creating}
          aria-label="New team workspace"
          title="New team workspace"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
        >
          <Plus size={16} aria-hidden />
        </button>
      </div>
      <p className="mt-1.5 flex items-center justify-between text-xs text-muted">
        <span>
          You are {current.role === 'owner' ? 'an' : 'a'} {current.role}
        </span>
        {current.kind === 'team' && current.role === 'owner' && (
          <button type="button" onClick={onManage} className="-my-1 inline-flex items-center gap-1 rounded px-2 py-1 text-accent hover:underline">
            <Users size={12} aria-hidden /> Members &amp; invites
          </button>
        )}
      </p>
    </div>
  )
}
