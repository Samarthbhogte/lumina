'use client'

import { useParams, useRouter } from 'next/navigation'

import { AuthShell, Field, FormError, PASSWORD_HINT, SubmitButton, useSubmit } from '@/components/AuthCard'
import { resetPassword } from '@/lib/api'

export default function ResetPage() {
  const { token } = useParams<{ token: string }>()
  const router = useRouter()
  const reset = useSubmit((f) => resetPassword(token, String(f.get('password'))), () => router.replace('/login'))
  return (
    <AuthShell title="Choose a new password" subtitle="This signs you out on every device.">
      <form onSubmit={reset.submit} aria-describedby={reset.error ? "form-error" : undefined} className="space-y-4">
        <Field label="New password" name="password" type="password" autoComplete="new-password" minLength={15} required hint={PASSWORD_HINT} />
        <FormError error={reset.error} />
        <SubmitButton busy={reset.busy}>Set password</SubmitButton>
      </form>
    </AuthShell>
  )
}
