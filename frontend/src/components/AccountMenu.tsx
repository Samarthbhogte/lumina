'use client'

import { LogOut } from 'lucide-react'
import { useRouter } from 'next/navigation'

import { signOut, type Me } from '@/lib/api'

export function AccountMenu({ me }: { me: Me }) {
  const router = useRouter()
  const left = Math.max(0, me.questions_per_day - me.questions_used_today)
  return (
    <div className="mb-3 flex items-center justify-between gap-2">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium" title={me.user.email}>
          {me.user.display_name}
        </p>
        <p className="text-xs text-muted">
          {left} of {me.questions_per_day} questions left today
        </p>
      </div>
      <button
        type="button"
        onClick={async () => {
          try {
            await signOut()
          } finally {
            router.replace('/login')
          }
        }}
        aria-label="Sign out"
        title="Sign out"
        className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
      >
        <LogOut size={15} aria-hidden />
      </button>
    </div>
  )
}
