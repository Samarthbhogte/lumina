'use client'

import dynamic from 'next/dynamic'

// The workspace restores the conversation from localStorage, so it renders on the client only.
const Workspace = dynamic(() => import('@/components/Workspace'), {
  ssr: false,
  loading: () => (
    <div className="flex h-dvh items-center justify-center text-sm text-muted">Loading Lumina…</div>
  ),
})

export default function Home() {
  return <Workspace />
}
