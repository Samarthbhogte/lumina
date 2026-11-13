'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { AuthShell, Field, FormError, PASSWORD_HINT, SubmitButton, useSubmit } from '@/components/AuthCard'
import { getHealth, signIn, signUp } from '@/lib/api'

export default function LoginPage() {
  const router = useRouter()
  const [setup, setSetup] = useState<boolean | null>(null)

  useEffect(() => {
    getHealth()
      .then((h) => setSetup(h.needs_setup))
      .catch(() => setSetup(false))
  }, [])

  const done = () => router.replace('/')
  const login = useSubmit((f) => signIn(String(f.get('email')), String(f.get('password'))), done)
  const create = useSubmit(
    (f) =>
      signUp({
        display_name: String(f.get('name')),
        email: String(f.get('email')),
        password: String(f.get('password')),
      }),
    done,
  )

  if (setup === null) return <AuthShell title="Lumina"><p role="status" className="text-sm text-muted">Loading…</p></AuthShell>

  if (setup) {
    return (
      <AuthShell
        title="Create the admin account"
        subtitle="You're the first person here. This account will own the existing library and can invite others."
      >
        <form onSubmit={create.submit} aria-describedby={create.error ? "form-error" : undefined} className="space-y-4">
          <Field label="Your name" name="name" autoComplete="name" required />
          <Field label="Email" name="email" type="email" autoComplete="email" required />
          <Field label="Password" name="password" type="password" autoComplete="new-password" minLength={15} required hint={PASSWORD_HINT} />
          <FormError error={create.error} />
          <SubmitButton busy={create.busy}>Create account</SubmitButton>
        </form>
      </AuthShell>
    )
  }

  return (
    <AuthShell title="Sign in" subtitle="New here? Ask a workspace owner for an invite link.">
      <form onSubmit={login.submit} aria-describedby={login.error ? "form-error" : undefined} className="space-y-4">
        <Field label="Email" name="email" type="email" autoComplete="email" required />
        <Field label="Password" name="password" type="password" autoComplete="current-password" required />
        <FormError error={login.error} />
        <SubmitButton busy={login.busy}>Sign in</SubmitButton>
      </form>
    </AuthShell>
  )
}
