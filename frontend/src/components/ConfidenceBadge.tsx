import { CircleCheck, CircleHelp, CircleMinus, ShieldAlert } from 'lucide-react'

import type { AskResult } from '@/lib/api'
import { cn } from '@/lib/utils'

// Confidence is how closely the cited passages match the question (retrieval similarity),
// so the labels describe source match rather than claiming the answer is "correct".
export function ConfidenceBadge({ result }: { result: AskResult }) {
  const base = 'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium'
  if (result.flagged)
    return (
      <span className={cn(base, 'bg-bad-soft text-bad')}>
        <ShieldAlert size={13} aria-hidden /> Blocked instruction
      </span>
    )
  if (!result.found)
    return (
      <span className={cn(base, 'bg-surface-2 text-muted')}>
        <CircleMinus size={13} aria-hidden /> Not in your documents
      </span>
    )
  const styles = {
    high: ['bg-good-soft text-good', CircleCheck, 'Strong source match'],
    medium: ['bg-warn-soft text-warn', CircleHelp, 'Partial source match'],
    low: ['bg-bad-soft text-bad', CircleHelp, 'Weak source match, verify'],
  } as const
  const [cls, Icon, label] = styles[result.confidence]
  return (
    <span
      className={cn(base, cls)}
      title="How closely the cited passages match your question. Always check the source for decisions."
    >
      <Icon size={13} aria-hidden /> {label}
    </span>
  )
}
