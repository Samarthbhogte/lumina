'use client'

import dynamic from 'next/dynamic'
import { useParams } from 'next/navigation'

// The workspace is fully client-side (session-bound data), so skip server rendering.
const Workspace = dynamic(() => import('@/components/Workspace'), {
  ssr: false,
  loading: () => <div className="flex h-dvh items-center justify-center text-sm text-muted">Loading Lumina…</div>,
})

export default function WorkspacePage() {
  const { wsId } = useParams<{ wsId: string }>()
  return <Workspace workspaceId={wsId} />
}
