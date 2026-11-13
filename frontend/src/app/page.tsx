'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { ApiError, getMe } from '@/lib/api'

const LAST_WORKSPACE = 'lumina.lastWorkspace'

export default function Home() {
  const router = useRouter()
  useEffect(() => {
    getMe()
      .then((me) => {
        let last: string | null = null
        try {
          last = localStorage.getItem(LAST_WORKSPACE)
        } catch {
          /* storage unavailable */
        }
        const target = me.workspaces.find((w) => w.id === last) ?? me.workspaces.find((w) => w.kind === 'personal')
        router.replace(target ? `/w/${target.id}` : '/login')
      })
      .catch((e) => router.replace(e instanceof ApiError && e.status === 401 ? '/login' : '/login'))
  }, [router])
  return <div className="flex h-dvh items-center justify-center text-sm text-muted">Loading Lumina…</div>
}
