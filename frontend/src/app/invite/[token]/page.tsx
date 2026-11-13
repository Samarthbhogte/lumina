'use client'

import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { AuthShell, Field, FormError, PASSWORD_HINT, SubmitButton, useSubmit } from '@/components/AuthCard'
import { acceptInvite, previewInvite, signIn, signUp, type Role } from '@/lib/api'

export default function InvitePage() {
  const { token } = useParams<{ token: string }>()
  const router = useRouter()
  const [invite, setInvite] = useState<{ workspace: string; role: Role; signed_in: boolean } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [haveAccount, setHaveAccount] = useState(false)

  useEffect(() => {
    previewInvite(token)
      .then(setInvite)
      .catch((e: Error) => setError(e.message))
  }, [token])

  const open = (wsId: string) => router.replace(`/w/${wsId}`)
  const accept = useSubmit(() => acceptInvite(token), (ws) => open(ws.id))
  const join = useSubmit(
    (f) =>
      signUp({
        display_name: String(f.get('name')),
        email: String(f.get('email')),
        password: String(f.get('password')),
        invite_token: token,
      }),
    () => router.replace('/'),
  )
  const login = useSubmit(async (f) => {
    await signIn(String(f.get('email')), String(f.get('password')))
    return acceptInvite(token)
  }, (ws) => open(ws.id))

  if (error) return <AuthShell title="Invite unavailable" subtitle={error}>{null}</AuthShell>
  if (!invite) return <AuthShell title="Lumina">{null}</AuthShell>

  const subtitle = `You've been invited to “${invite.workspace}” as ${invite.role === 'owner' ? 'an' : 'a'} ${invite.role}.`

  if (invite.signed_in) {
    return (
      <AuthShell title="Join workspace" subtitle={subtitle}>
        <form onSubmit={accept.submit} className="space-y-4">
          <FormError error={accept.error} />
          <SubmitButton busy={accept.busy}>Accept invite</SubmitButton>
        </form>
      </AuthShell>
    )
  }

  return (
    <AuthShell title="Join workspace" subtitle={subtitle}>
      {haveAccount ? (
        <form onSubmit={login.submit} className="space-y-4">
          <Field label="Email" name="email" type="email" autoComplete="email" required />
          <Field label="Password" name="password" type="password" autoComplete="current-password" required />
          <FormError error={login.error} />
          <SubmitButton busy={login.busy}>Sign in and join</SubmitButton>
        </form>
      ) : (
        <form onSubmit={join.submit} className="space-y-4">
          <Field label="Your name" name="name" autoComplete="name" required />
          <Field label="Email" name="email" type="email" autoComplete="email" required />
          <Field label="Password" name="password" type="password" autoComplete="new-password" minLength={15} required hint={PASSWORD_HINT} />
          <FormError error={join.error} />
          <SubmitButton busy={join.busy}>Create account and join</SubmitButton>
        </form>
      )}
      <button type="button" onClick={() => setHaveAccount((v) => !v)} className="mt-4 text-sm text-accent underline">
        {haveAccount ? 'I need an account' : 'I already have an account'}
      </button>
    </AuthShell>
  )
}
